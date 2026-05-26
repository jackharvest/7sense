mod archive;
mod config;
mod monitor;
mod notifier;

use std::sync::{Arc, Mutex};
use monitor::ExtractionSummary;
use notifier::fmt_eta;

// The app icon is compiled directly into the binary so there's no external file dependency.
static ICON_BYTES: &[u8] = include_bytes!("../../sevensense/icon.png");

// ── tray icon ────────────────────────────────────────────────────────────────
// ksni expects ARGB32 pixel data in big-endian byte order.
// The PNG is decoded at startup and converted from RGBA (PNG's native order).

fn load_tray_icon() -> Vec<ksni::Icon> {
    use png::ColorType;
    let decoder = png::Decoder::new(std::io::Cursor::new(ICON_BYTES));
    let mut reader = match decoder.read_info() {
        Ok(r)  => r,
        Err(_) => return vec![],
    };
    let mut pixel_buf = vec![0u8; reader.output_buffer_size()];
    let frame_info = match reader.next_frame(&mut pixel_buf) {
        Ok(i)  => i,
        Err(_) => return vec![],
    };
    let (width, height) = (frame_info.width as i32, frame_info.height as i32);
    let pixels = &pixel_buf[..frame_info.buffer_size()];

    // Convert RGBA or RGB → ARGB32 big-endian as required by the StatusNotifierItem spec.
    let argb_data: Vec<u8> = match frame_info.color_type {
        ColorType::Rgba => pixels.chunks(4)
            .flat_map(|p| [p[3], p[0], p[1], p[2]])
            .collect(),
        ColorType::Rgb => pixels.chunks(3)
            .flat_map(|p| [255u8, p[0], p[1], p[2]])
            .collect(),
        _ => return vec![],
    };

    vec![ksni::Icon { width, height, data: argb_data }]
}

// ── shared state ─────────────────────────────────────────────────────────────
// The monitor thread writes here; the tray thread reads it to build tooltips and menus.

type SharedSummaries = Arc<Mutex<Vec<ExtractionSummary>>>;

// ── tray ─────────────────────────────────────────────────────────────────────

struct Tray {
    state: SharedSummaries,
}

impl ksni::Tray for Tray {
    fn id(&self) -> String { "7sense".into() }
    fn title(&self) -> String { "7Sense".into() }

    fn icon_pixmap(&self) -> Vec<ksni::Icon> {
        load_tray_icon()
    }

    fn tool_tip(&self) -> ksni::ToolTip {
        let summaries = self.state.lock().unwrap();
        let (title, description) = build_tooltip_text(&summaries);
        drop(summaries);
        ksni::ToolTip {
            icon_name: String::new(),
            icon_pixmap: vec![],
            title,
            description,
        }
    }

    fn menu(&self) -> Vec<ksni::MenuItem<Self>> {
        use ksni::menu::*;
        let summaries = self.state.lock().unwrap();
        let status_label = match summaries.len() {
            0 => "No active extractions".into(),
            1 => "1 active extraction".into(),
            n => format!("{} active extractions", n),
        };
        drop(summaries);

        vec![
            // Status line (disabled — informational only)
            StandardItem {
                label: status_label,
                enabled: false,
                ..Default::default()
            }.into(),
            MenuItem::Separator,
            StandardItem {
                label: "Settings…".into(),
                activate: Box::new(|_| open_launcher_window("--settings")),
                ..Default::default()
            }.into(),
            StandardItem {
                label: "About 7Sense".into(),
                activate: Box::new(|_| open_launcher_window("--about")),
                ..Default::default()
            }.into(),
            MenuItem::Separator,
            StandardItem {
                label: "Exit".into(),
                activate: Box::new(|_| std::process::exit(0)),
                ..Default::default()
            }.into(),
        ]
    }
}

// ── launcher helpers ──────────────────────────────────────────────────────────
// The daemon binary lives at:  <project>/7sense-daemon/target/release/7sense-daemon
// The Python launcher lives at: <project>/7sense
// We navigate up four directories from our own executable to find the launcher.

fn find_launcher() -> Option<std::path::PathBuf> {
    let our_exe = std::env::current_exe().ok()?;
    let project_root = our_exe.parent()?.parent()?.parent()?.parent()?;
    let launcher = project_root.join("7sense");
    if launcher.exists() { Some(launcher) } else { None }
}

fn open_launcher_window(flag: &str) {
    if let Some(launcher) = find_launcher() {
        let _ = std::process::Command::new(&launcher).arg(flag).spawn();
    }
}

// ── tooltip text ──────────────────────────────────────────────────────────────

fn build_tooltip_text(summaries: &[ExtractionSummary]) -> (String, String) {
    match summaries.len() {
        0 => (
            "7Sense".into(),
            "Standing by — nothing extracting.".into(),
        ),
        1 => {
            let s = &summaries[0];
            let progress_text = format_summary_line(s);
            (
                format!("7Sense  —  {}", progress_text),
                s.archive_name.clone(),   // filename shown as the subtitle
            )
        }
        n => {
            let title = format!("7Sense  —  {} active extractions", n);
            let lines = summaries.iter()
                .map(|s| format!("{}  —  {}", s.archive_name, format_summary_line(s)))
                .collect::<Vec<_>>()
                .join("\n");
            (title, lines)
        }
    }
}

fn format_summary_line(summary: &ExtractionSummary) -> String {
    match summary.pct {
        None    => "Extracting…".into(),
        Some(p) => {
            let pct_str = format!("{}%", (p * 100.0) as u32);
            match summary.eta_secs {
                Some(eta) => format!("{}  ·  {} left", pct_str, fmt_eta(eta)),
                None      => pct_str,
            }
        }
    }
}

// ── main ─────────────────────────────────────────────────────────────────────

fn main() {
    let shared_state: SharedSummaries = Arc::new(Mutex::new(vec![]));

    // Spawn the monitoring thread. It reads /proc on every tick and writes
    // the current extraction summaries into shared_state for the tray to read.
    let state_for_monitor = Arc::clone(&shared_state);
    std::thread::spawn(move || {
        monitor::run(move |new_summaries| {
            *state_for_monitor.lock().unwrap() = new_summaries;
        });
    });

    // Start the tray icon. ksni drives its own D-Bus event loop internally,
    // so we just hand it a handle and park the main thread.
    let tray = Tray { state: shared_state };
    let _tray_service = ksni::TrayService::new(tray).spawn();

    // Park the main thread forever — the tray and monitor threads keep everything alive.
    loop { std::thread::park(); }
}
