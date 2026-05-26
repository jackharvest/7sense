use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use crate::archive;
use crate::config::Config;
use crate::notifier;

// Sent to the tray thread each poll cycle so the tooltip and menu stay current.
#[derive(Clone)]
pub struct ExtractionSummary {
    pub archive_name: String,
    pub pct: Option<f64>,       // None = we have no size info yet
    pub eta_secs: Option<f64>,  // None = too early or too close to bother showing
}

// Everything we know about one active extraction process.
struct Tracker {
    #[allow(dead_code)]  // stored for future debugging/logging; the HashMap key is also the pid
    pid: u32,
    archive_path: PathBuf,
    dest_dir: PathBuf,
    total_bytes: Option<u64>,   // expected uncompressed size; None if we couldn't pre-scan
    start: Instant,
    notification_id: Option<u32>, // the ID from notify-send --print-id, used to replace in-place
}

impl Tracker {
    // Sum all file sizes currently on disk in the destination directory.
    // This is how we measure extraction progress — watch the folder fill up.
    fn dest_bytes(&self) -> u64 {
        dir_bytes(&self.dest_dir)
    }

    fn progress(&self) -> Option<f64> {
        let total = self.total_bytes?;
        if total == 0 { return None; }
        // Cap at 0.99 — the final few files can appear all at once,
        // and we don't want to flash 100% before the process has actually exited.
        Some((self.dest_bytes() as f64 / total as f64).min(0.99))
    }

    fn eta_secs(&self, pct: f64) -> Option<f64> {
        // Need at least 2% done before elapsed/pct gives a meaningful estimate.
        if pct < 0.02 { return None; }
        let elapsed = self.start.elapsed().as_secs_f64();
        let remaining = (elapsed / pct - elapsed).max(0.0);
        // Skip the countdown for the last few seconds — it just flickers annoyingly.
        if remaining > 5.0 { Some(remaining) } else { None }
    }

    fn build_summary(&self) -> ExtractionSummary {
        let pct = self.progress();
        let eta_secs = pct.and_then(|p| self.eta_secs(p));
        ExtractionSummary {
            archive_name: self.archive_path
                .file_name().unwrap_or_default()
                .to_string_lossy().into_owned(),
            pct,
            eta_secs,
        }
    }
}

// Recursively sum the sizes of all regular files under a directory.
fn dir_bytes(dir: &Path) -> u64 {
    let Ok(entries) = std::fs::read_dir(dir) else { return 0 };
    entries.flatten().map(|entry| {
        let path = entry.path();
        if path.is_dir() {
            dir_bytes(&path)
        } else {
            path.metadata().map(|m| m.len()).unwrap_or(0)
        }
    }).sum()
}

// Main monitoring loop — runs on a background thread.
// Calls `on_update` with the current list of active extractions after every poll cycle.
pub fn run<F>(mut on_update: F)
where
    F: FnMut(Vec<ExtractionSummary>),
{
    let mut active: HashMap<u32, Tracker> = HashMap::new();

    loop {
        // Reload config on every cycle so settings changes take effect immediately
        // without needing to restart the daemon.
        let config = Config::load();
        let poll_interval = Duration::from_secs_f64(config.poll_interval);
        let min_notify_secs = config.min_notify_seconds;

        // Check /proc for new archive processes that started since the last cycle.
        for (pid, tool_name, cmdline, working_dir) in scan_procs() {
            if active.contains_key(&pid) { continue; }
            if !config.tool_enabled(&tool_name) { continue; }
            if !archive::is_extract_command(&tool_name, &cmdline) { continue; }

            let Some(archive_path) = archive::find_archive_path(&tool_name, &cmdline) else { continue };
            // Resolve relative paths against the process's working directory.
            let archive_path = if archive_path.is_absolute() {
                archive_path
            } else {
                working_dir.join(&archive_path)
            };

            let dest_dir = archive::find_dest_dir(&tool_name, &cmdline, &working_dir);
            let total_bytes = archive::scan_total_bytes(&tool_name, &archive_path);

            active.insert(pid, Tracker {
                pid,
                archive_path,
                dest_dir,
                total_bytes,
                start: Instant::now(),
                notification_id: None,
            });
        }

        // Update each active tracker; collect any that have finished.
        let mut finished_pids = vec![];

        for (&pid, tracker) in active.iter_mut() {
            if !pid_alive(pid) {
                // Process exited — fire the "done" notification if it ran long enough
                // and we had already shown a progress notification for it.
                if tracker.start.elapsed().as_secs() >= min_notify_secs
                    && tracker.notification_id.is_some()
                {
                    let archive_name = tracker.archive_path.file_name()
                        .unwrap_or_default().to_string_lossy();
                    notifier::show_complete(&archive_name, tracker.start.elapsed());
                }
                finished_pids.push(pid);
                continue;
            }

            // Don't spam notifications for quick extractions — wait for min_notify_secs.
            if tracker.start.elapsed().as_secs() < min_notify_secs { continue; }

            let pct = tracker.progress();
            let eta = pct.and_then(|p| tracker.eta_secs(p));
            let archive_name = tracker.archive_path.file_name()
                .unwrap_or_default().to_string_lossy();

            // Build the notification title: "47%  ·  2m 13s left" (or just "Extracting…")
            let notification_title = match pct {
                Some(p) => {
                    let pct_str = format!("{}%", (p * 100.0) as u32);
                    match eta {
                        Some(e) => format!("{}  ·  {} left", pct_str, notifier::fmt_eta(e)),
                        None    => pct_str,
                    }
                }
                None => "Extracting…".into(),
            };

            // Pass our existing notification ID so notify-send replaces it in-place
            // rather than stacking up a new popup every cycle.
            let new_id = notifier::show_progress(&notification_title, &archive_name, tracker.notification_id);
            if new_id.is_some() {
                tracker.notification_id = new_id;
            }
        }

        for pid in finished_pids {
            active.remove(&pid);
        }

        // Push a summary of all active extractions to the tray thread.
        // Only include ones that have been running long enough to care about.
        let summaries: Vec<ExtractionSummary> = active.values()
            .filter(|tracker| {
                tracker.notification_id.is_some()
                    || tracker.start.elapsed().as_secs() >= min_notify_secs
            })
            .map(|tracker| tracker.build_summary())
            .collect();

        on_update(summaries);

        std::thread::sleep(poll_interval);
    }
}

fn pid_alive(pid: u32) -> bool {
    // /proc/<pid> disappears the moment a process exits on Linux.
    Path::new(&format!("/proc/{}", pid)).exists()
}

// Walk /proc and return info on any archive tool processes currently running.
fn scan_procs() -> Vec<(u32, String, Vec<String>, PathBuf)> {
    let Ok(proc_entries) = std::fs::read_dir("/proc") else { return vec![] };

    proc_entries.flatten().filter_map(|entry| {
        // /proc entries that are all digits are process directories.
        let pid: u32 = entry.file_name().to_str()?.parse().ok()?;

        // Read the process name from /proc/<pid>/comm (just the executable name, no path).
        let tool_name = std::fs::read_to_string(format!("/proc/{}/comm", pid))
            .ok()?.trim().to_owned();

        // Skip immediately if it's not one of the archive tools we care about.
        if !archive::SUPPORTED_TOOLS.contains(&tool_name.as_str()) { return None; }

        // Read the full command line (null-separated arguments).
        let raw_cmdline = std::fs::read(format!("/proc/{}/cmdline", pid)).ok()?;
        let cmdline: Vec<String> = raw_cmdline.split(|&byte| byte == 0)
            .filter(|arg| !arg.is_empty())
            .map(|arg| String::from_utf8_lossy(arg).into_owned())
            .collect();

        // The process's working directory — needed to resolve relative archive paths.
        let working_dir = std::fs::read_link(format!("/proc/{}/cwd", pid)).ok()?;

        Some((pid, tool_name, cmdline, working_dir))
    }).collect()
}
