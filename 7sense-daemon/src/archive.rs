use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::process::Command;

// All process names we watch for in /proc.
// If a new tool shows up here it also needs entries in the functions below.
pub const SUPPORTED_TOOLS: &[&str] = &["7z", "7zz", "tar", "bsdtar", "unzip", "unar", "unrar"];

// Returns true if this command line is actually doing an extraction
// (as opposed to listing, testing, or some other operation).
pub fn is_extract_command(tool_name: &str, cmdline: &[String]) -> bool {
    match tool_name {
        // 7z x = extract with full paths, 7z e = extract flat
        "7z" | "7zz" => cmdline.iter().any(|arg| arg == "x" || arg == "e"),

        // tar: look for the -x / --extract flag anywhere in the first few args
        "tar" | "bsdtar" => cmdline.iter().any(|arg| {
            let flag = arg.trim_start_matches('-');
            flag.contains('x') && !flag.contains('c') && !flag.is_empty()
        }),

        // unzip: it's always extracting unless -l (list), -v (verbose list), or -Z (zipinfo mode)
        "unzip" => !cmdline.iter().any(|arg| arg == "-l" || arg == "-v" || arg == "-Z"),

        // unar only extracts — lsar is the separate listing tool
        "unar" => true,

        // unrar x = extract with paths, unrar e = extract flat
        "unrar" => cmdline.iter().any(|arg| arg == "x" || arg == "e"),

        _ => false,
    }
}

// Pull the archive file path out of the process's command line.
// Returns None if we can't figure it out (malformed args, piped input, etc.)
pub fn find_archive_path(tool_name: &str, cmdline: &[String]) -> Option<PathBuf> {
    let args = &cmdline[1.min(cmdline.len())..];

    match tool_name {
        // Layout: 7z x [-switches] archive.7z
        "7z" | "7zz" | "unrar" => {
            let mut past_verb = false;
            for arg in args {
                if !past_verb {
                    if arg == "x" || arg == "e" { past_verb = true; }
                    continue;
                }
                if !arg.starts_with('-') { return Some(PathBuf::from(arg)); }
            }
            None
        }

        // Layout: tar -xzf archive.tar.gz  or  tar xf archive.tar.gz  or  tar --file=...
        "tar" | "bsdtar" => {
            let mut args_iter = args.iter();
            while let Some(arg) = args_iter.next() {
                // --file archive  or  -f archive
                if arg == "-f" || arg == "--file" {
                    return args_iter.next().map(PathBuf::from);
                }
                // --file=archive
                if let Some(path) = arg.strip_prefix("--file=") {
                    return Some(PathBuf::from(path));
                }
                // Bundled short flags that include f: -xzf, -xf, -xJvf, etc.
                if arg.starts_with('-') && !arg.starts_with("--") && arg.contains('f') {
                    return args_iter.next().map(PathBuf::from);
                }
                // Old-style no-dash flags: tar xf, tar xzf (no leading dash, has f, short)
                if !arg.starts_with('-') && arg.contains('f') && arg.len() <= 8 {
                    return args_iter.next().map(PathBuf::from);
                }
            }
            None
        }

        // Layout: unzip [-options] archive.zip [files...]
        "unzip" => args.iter().find(|arg| !arg.starts_with('-')).map(PathBuf::from),

        // Layout: unar [options] archive [files...]
        // Some unar flags consume the next argument as a value — we need to skip those values
        // so we don't mistake a flag value for the archive path.
        "unar" => {
            const VALUE_FLAGS: &[&str] = &[
                "-o", "-output-directory",
                "-p", "-password",
                "-e", "-encoding",
                "-E", "-password-encoding",
                "-k", "-forks",
            ];
            let mut skip_next = false;
            for arg in args {
                if skip_next { skip_next = false; continue; }
                if VALUE_FLAGS.contains(&arg.as_str()) { skip_next = true; continue; }
                // Boolean flags (like -D / -no-directory) do NOT consume the next argument
                if !arg.starts_with('-') { return Some(PathBuf::from(arg)); }
            }
            None
        }

        _ => None,
    }
}

// Find where extracted files will land. Falls back to the process's working directory.
pub fn find_dest_dir(tool_name: &str, cmdline: &[String], working_dir: &Path) -> PathBuf {
    let args = &cmdline[1.min(cmdline.len())..];

    match tool_name {
        // 7z -o<path> (no space between -o and the path)
        "7z" | "7zz" => {
            for arg in args {
                if let Some(path) = arg.strip_prefix("-o") {
                    if !path.is_empty() { return PathBuf::from(path); }
                }
            }
            working_dir.to_path_buf()
        }

        // tar -C <path> or --directory <path>
        "tar" | "bsdtar" => {
            let mut args_iter = args.iter();
            while let Some(arg) = args_iter.next() {
                if arg == "-C" || arg == "--directory" {
                    if let Some(path) = args_iter.next() { return PathBuf::from(path); }
                }
                if let Some(path) = arg.strip_prefix("-C") {
                    if !path.is_empty() { return PathBuf::from(path); }
                }
            }
            working_dir.to_path_buf()
        }

        // unzip -d <path>
        "unzip" => {
            let mut args_iter = args.iter();
            while let Some(arg) = args_iter.next() {
                if arg == "-d" {
                    if let Some(path) = args_iter.next() { return PathBuf::from(path); }
                }
            }
            working_dir.to_path_buf()
        }

        // unar -o <path>  or  -output-directory <path>
        "unar" => {
            let mut args_iter = args.iter();
            while let Some(arg) = args_iter.next() {
                if arg == "-o" || arg == "-output-directory" {
                    if let Some(path) = args_iter.next() { return PathBuf::from(path); }
                }
            }
            working_dir.to_path_buf()
        }

        // unrar extracts into cwd by default; optional trailing dest arg not commonly used
        _ => working_dir.to_path_buf(),
    }
}

// Pre-scan an archive to get its total uncompressed size.
// Returns None if the format is unknown, the file is unreadable, or the scan times out.
pub fn scan_total_bytes(_tool_name: &str, archive_path: &Path) -> Option<u64> {
    let path_lower = archive_path.to_string_lossy().to_lowercase();

    // Route by file extension — fast header reads where possible.
    if path_lower.ends_with(".tar.gz") || path_lower.ends_with(".tgz") {
        return gz_size(archive_path);
    }
    if path_lower.ends_with(".tar.xz") || path_lower.ends_with(".txz") {
        return xz_size(archive_path);
    }
    if path_lower.ends_with(".zip") {
        return zip_size(archive_path);
    }

    // .7z, .rar, .tar.bz2, and anything else: ask 7z to list it.
    // 7z can read RAR files, so this covers unar/unrar too.
    scan_via_7z(archive_path)
}

// Read the ISIZE field from the last 4 bytes of a gzip stream.
// This is a mod-2^32 count of the uncompressed bytes — O(1), no decompression needed.
fn gz_size(archive_path: &Path) -> Option<u64> {
    let mut file = std::fs::File::open(archive_path).ok()?;
    let file_size = file.metadata().ok()?.len();
    if file_size < 4 { return None; }

    file.seek(SeekFrom::End(-4)).ok()?;
    let mut buf = [0u8; 4];
    file.read_exact(&mut buf).ok()?;
    let isize_field = u32::from_le_bytes(buf) as u64;

    // ISIZE wraps at 2^32. If the file is huge and the field is tiny, assume one wrap.
    let uncompressed = if isize_field < file_size / 4 && file_size > 4_000_000_000 {
        isize_field + (1 << 32)
    } else {
        isize_field
    };

    Some(uncompressed)
}

// Ask xz for the uncompressed size without decompressing anything.
// xz --list --robot reads only the stream index blocks.
fn xz_size(archive_path: &Path) -> Option<u64> {
    let output = Command::new("xz")
        .args(["--list", "--robot", archive_path.to_str()?])
        .output().ok()?;

    // The "totals" line from --robot output looks like:
    //   totals  <blocks>  <compressed>  <uncompressed>  <ratio>  <check>  ...
    // Column 5 (0-indexed) is the uncompressed size.
    std::str::from_utf8(&output.stdout).ok()?
        .lines()
        .find(|line| line.starts_with("totals\t"))
        .and_then(|line| line.split('\t').nth(5))
        .and_then(|value| value.parse().ok())
}

// Ask 7z to list the archive and sum all the "Size" fields.
// Works for .7z, .rar, .tar.bz2, and most other formats 7z can open.
fn scan_via_7z(archive_path: &Path) -> Option<u64> {
    let output = Command::new("7z")
        .args(["l", "-slt", archive_path.to_str()?])
        .output().ok()?;

    let text = std::str::from_utf8(&output.stdout).ok()?;
    let total: u64 = text.lines()
        .filter_map(|line| line.strip_prefix("Size = "))
        .filter_map(|value| value.trim().parse::<u64>().ok())
        .sum();

    if total > 0 { Some(total) } else { None }
}

// Ask unzip for the total uncompressed size from the ZIP central directory.
fn zip_size(archive_path: &Path) -> Option<u64> {
    let output = Command::new("unzip")
        .args(["-l", archive_path.to_str()?])
        .output().ok()?;

    // The last non-empty line from `unzip -l` looks like:
    //   12345678  42 files
    std::str::from_utf8(&output.stdout).ok()?
        .lines()
        .rev()
        .find(|line| !line.trim().is_empty())
        .and_then(|line| line.split_whitespace().next())
        .and_then(|first_token| first_token.parse().ok())
}
