use std::time::Duration;
use std::sync::OnceLock;
use std::path::PathBuf;

// The icon PNG is compiled into the binary. On first use we write it to a temp
// file so notify-send can reference it by path.
static ICON_BYTES: &[u8] = include_bytes!("../../sevensense/icon.png");

fn icon_path() -> &'static str {
    static CACHED_PATH: OnceLock<PathBuf> = OnceLock::new();
    CACHED_PATH.get_or_init(|| {
        let temp_dir = std::env::temp_dir().join("7sense");
        std::fs::create_dir_all(&temp_dir).unwrap_or(());
        let icon_file = temp_dir.join("icon.png");
        std::fs::write(&icon_file, ICON_BYTES).unwrap_or(());
        icon_file
    }).to_str().unwrap_or("/tmp/7sense/icon.png")
}

// Show or update a progress notification.
// If replace_id is Some, notify-send replaces the existing notification in-place
// instead of stacking a new popup on every poll cycle.
// Returns the notification ID assigned by the notification daemon (via --print-id).
pub fn show_progress(title: &str, body: &str, replace_id: Option<u32>) -> Option<u32> {
    let icon_flag = format!("--icon={}", icon_path());
    let mut cmd = std::process::Command::new("notify-send");
    cmd.args([
        "--print-id",
        "--app-name=7Sense",
        "--urgency=low",
        "--expire-time=20000",  // 20s safety expiry — cleans up if the daemon crashes
        &icon_flag,
    ]);
    if let Some(existing_id) = replace_id {
        cmd.arg(format!("--replace-id={}", existing_id));
    }
    cmd.args([title, body]);

    let output = cmd.output().ok()?;
    std::str::from_utf8(&output.stdout).ok()?.trim().parse().ok()
}

// Show a "Done" notification that auto-dismisses after 7 seconds.
pub fn show_complete(archive_name: &str, elapsed: Duration) {
    let icon_flag = format!("--icon={}", icon_path());
    let title = format!("Done  ·  {}", fmt_duration(elapsed));
    let _ = std::process::Command::new("notify-send")
        .args([
            "--app-name=7Sense",
            "--urgency=normal",
            "--expire-time=7000",
            &icon_flag,
            &title,
            archive_name,
        ])
        .spawn();
}

pub fn fmt_duration(duration: Duration) -> String {
    let total_secs = duration.as_secs();
    if total_secs < 60 {
        format!("{}s", total_secs)
    } else {
        format!("{}m {}s", total_secs / 60, total_secs % 60)
    }
}

// fmt_eta formats a remaining-time estimate for display in the notification title.
pub fn fmt_eta(remaining_secs: f64) -> String {
    fmt_duration(Duration::from_secs(remaining_secs as u64))
}
