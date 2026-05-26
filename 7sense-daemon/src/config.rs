use std::path::PathBuf;
use serde::Deserialize;

// Mirrors the JSON written by the Python side at ~/.config/7sense/config.json.
// The daemon re-reads this on every poll cycle, so settings changes in the UI
// take effect immediately without a restart.
//
// All fields have defaults (via serde) so missing keys in an older config file
// don't cause errors — handy when new settings are added in a later version.
#[derive(Debug, Deserialize)]
pub struct Config {
    #[serde(default = "yes")] pub watch_7z:            bool,
    #[serde(default = "yes")] pub watch_tar:           bool,
    #[serde(default = "yes")] pub watch_unzip:         bool,
    #[serde(default = "yes")] pub watch_unrar:         bool,
    #[serde(default = "default_poll_interval")] pub poll_interval:       f64,
    #[serde(default = "default_min_notify_secs")] pub min_notify_seconds: u64,
    #[serde(default = "yes")]
    #[allow(dead_code)]  // read by the Python settings UI; Rust daemon always shows tray for now
    pub tray_always_visible: bool,
}

fn yes() -> bool { true }
fn default_poll_interval() -> f64 { 1.5 }
fn default_min_notify_secs() -> u64 { 3 }

impl Default for Config {
    fn default() -> Self {
        // Deserializing an empty object triggers all the serde defaults above.
        serde_json::from_str("{}").unwrap()
    }
}

impl Config {
    pub fn load() -> Self {
        let config_file = config_file_path();
        std::fs::read_to_string(&config_file)
            .ok()
            .and_then(|contents| serde_json::from_str(&contents).ok())
            .unwrap_or_default()
    }

    // Returns true if extractions from this tool should be monitored.
    pub fn tool_enabled(&self, tool_name: &str) -> bool {
        match tool_name {
            "7z"  | "7zz"    => self.watch_7z,
            "tar" | "bsdtar" => self.watch_tar,
            "unzip"          => self.watch_unzip,
            "unar"| "unrar"  => self.watch_unrar,
            _                => true,
        }
    }
}

pub fn config_file_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".into());
    PathBuf::from(home).join(".config/7sense/config.json")
}
