#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    fs,
    io::{self, Read, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

use sha2::{Digest, Sha256};
use tauri::Manager;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

const APP_VERSION: &str = "0.14.13-paper-trading-repair";
const READY_MARKER: &str = ".sre01413-ready";
const CREATE_NO_WINDOW: u32 = 0x08000000;

fn sha256_file(path: &Path) -> Result<String, String> {
    let mut file = fs::File::open(path).map_err(|e| format!("Cannot open runtime bundle for hashing: {e}"))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 1024 * 1024];
    loop {
        let read = file.read(&mut buffer).map_err(|e| format!("Cannot hash runtime bundle: {e}"))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}
fn append_log(log_path: &Path, message: &str) {
    if let Ok(mut file) = fs::OpenOptions::new().create(true).append(true).open(log_path) {
        let _ = writeln!(file, "{message}");
        let _ = file.flush();
    }
}

fn marker_fingerprint(marker_path: &Path) -> Option<String> {
    let text = fs::read_to_string(marker_path).ok()?;
    text.lines()
        .find_map(|line| line.strip_prefix("bundle_sha256=").map(str::to_owned))
}

fn extract_engine(zip_path: &Path, destination: &Path, log_path: &Path) -> Result<(PathBuf, String), String> {
    let packaged_fingerprint = sha256_file(zip_path)?;
    let marker_path = destination.join(READY_MARKER);
    let extracted_fingerprint = marker_fingerprint(&marker_path);
    let extraction_required = extracted_fingerprint.as_deref() != Some(packaged_fingerprint.as_str())
        || !destination.join("run_modern_ui.py").exists();
    append_log(log_path, &format!("PACKAGED_RUNTIME_FINGERPRINT={packaged_fingerprint}"));
    append_log(log_path, &format!("EXTRACTED_RUNTIME_FINGERPRINT={}", extracted_fingerprint.as_deref().unwrap_or("MISSING")));
    append_log(log_path, &format!("EXTRACTION_REQUIRED={}", if extraction_required { "YES" } else { "NO" }));
    if !extraction_required {
        append_log(log_path, "EXTRACTION_OUTCOME=REUSED_VERIFIED");
        append_log(log_path, &format!("RUNTIME_PATH_LAUNCHED={}", destination.display()));
        return Ok((destination.to_path_buf(), packaged_fingerprint));
    }
    let parent = destination.parent().ok_or("No engine parent directory")?;
    fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    let staging = parent.join(format!("engine-v01413-staging-{}", std::process::id()));
    if staging.exists() {
        fs::remove_dir_all(&staging).map_err(|e| e.to_string())?;
    }
    fs::create_dir_all(&staging).map_err(|e| e.to_string())?;

    let file = fs::File::open(zip_path)
        .map_err(|e| format!("Cannot open bundled engine source: {e}"))?;
    let mut archive = zip::ZipArchive::new(file)
        .map_err(|e| format!("Invalid bundled engine source: {e}"))?;
    archive
        .extract(&staging)
        .map_err(|e| format!("Cannot extract bundled engine source: {e}"))?;

    if !staging.join("run_modern_ui.py").exists() {
        return Err("Bundled engine source is missing run_modern_ui.py".into());
    }
    fs::write(
        staging.join(READY_MARKER),
        format!("version={APP_VERSION}\nbundle_sha256={packaged_fingerprint}\n"),
    )
    .map_err(|e| format!("Cannot write staged runtime identity: {e}"))?;

    let retired = parent.join(format!("engine-v01413-retired-{}", std::process::id()));
    if retired.exists() {
        fs::remove_dir_all(&retired).map_err(|e| e.to_string())?;
    }
    if destination.exists() {
        fs::rename(destination, &retired)
            .map_err(|e| format!("Cannot retire stale runtime atomically: {e}"))?;
    }
    if let Err(error) = fs::rename(&staging, destination) {
        if retired.exists() && !destination.exists() {
            let _ = fs::rename(&retired, destination);
        }
        return Err(format!("Cannot promote verified runtime atomically: {error}"));
    }
    let promoted = marker_fingerprint(&destination.join(READY_MARKER));
    if promoted.as_deref() != Some(packaged_fingerprint.as_str()) {
        return Err("Promoted runtime fingerprint verification failed".into());
    }
    if retired.exists() {
        let _ = fs::remove_dir_all(&retired);
    }
    append_log(log_path, "EXTRACTION_OUTCOME=SUCCESS");
    append_log(log_path, &format!("RUNTIME_PATH_LAUNCHED={}", destination.display()));
    Ok((destination.to_path_buf(), packaged_fingerprint))
}

fn choose_free_port() -> Result<u16, String> {
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .map_err(|e| format!("Cannot allocate local port: {e}"))?;
    let port = listener
        .local_addr()
        .map_err(|e| format!("Cannot read local port: {e}"))?
        .port();
    drop(listener);
    Ok(port)
}

fn health_matches(port: u16, expected_version: &str) -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(300)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(700)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(700)));
    let request = format!(
        "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    response.contains("\"status\":\"ok\"")
        && response.contains("\"app_version\"")
        && response.contains(expected_version)
}

fn wait_for_server(
    child: &mut Child,
    port: u16,
    expected_version: &str,
    timeout: Duration,
) -> Result<(), String> {
    let started = Instant::now();
    while started.elapsed() < timeout {
        if let Ok(Some(status)) = child.try_wait() {
            return Err(format!("Local engine exited during startup ({status})."));
        }
        if health_matches(port, expected_version) {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(180));
    }
    Err(format!(
        "Local engine did not become ready with version {expected_version} within 45 seconds."
    ))
}

fn python_command() -> Result<Command, String> {
    for candidate in ["python.exe", "python"] {
        let mut probe = Command::new(candidate);
        probe.arg("--version").stdout(Stdio::null()).stderr(Stdio::null());
        #[cfg(target_os = "windows")]
        probe.creation_flags(CREATE_NO_WINDOW);
        if !probe.status().map(|s| s.success()).unwrap_or(false) {
            continue;
        }

        let mut modules = Command::new(candidate);
        modules
            .args(["-c", "import fastapi, uvicorn, requests"])
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        #[cfg(target_os = "windows")]
        modules.creation_flags(CREATE_NO_WINDOW);

        if !modules.status().map(|s| s.success()).unwrap_or(false) {
            let mut pip = Command::new(candidate);
            pip.args([
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "fastapi==0.128.2",
                "uvicorn==0.48.0",
                "requests>=2.32,<3",
            ])
            .stdout(Stdio::null())
            .stderr(Stdio::null());
            #[cfg(target_os = "windows")]
            pip.creation_flags(CREATE_NO_WINDOW);
            if !pip.status().map(|s| s.success()).unwrap_or(false) {
                return Err("Python is installed, but the local UI runtime could not be installed. Check internet access and reopen the app.".into());
            }
        }

        let mut cmd = Command::new(candidate);
        #[cfg(target_os = "windows")]
        cmd.creation_flags(CREATE_NO_WINDOW);
        return Ok(cmd);
    }
    Err("Python was not found. Install Python 3.12+ and reopen the app.".into())
}

fn main() {
    let child_state: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(None));
    let state_for_setup = child_state.clone();
    let state_for_exit = child_state.clone();

    tauri::Builder::default()
        .setup(move |app| {
            let window = app
                .get_webview_window("main")
                .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "Main window was not created"))?;
            let resource_dir = app.path().resource_dir()?;
            let zip_path = resource_dir
                .join("resources")
                .join("SRE01413_ENGINE_SOURCE.zip");

            let local_base = std::env::var_os("LOCALAPPDATA")
                .map(PathBuf::from)
                .unwrap_or_else(|| {
                    app.path()
                        .app_local_data_dir()
                        .unwrap_or_else(|_| PathBuf::from("."))
                });
            let shared_app_data = local_base.join("StockRecommendationEngine");
            let engine_root = shared_app_data.join("native-engine-0.14.13");

            thread::spawn(move || {
                let result: Result<(), String> = (|| {
                    fs::create_dir_all(&shared_app_data).map_err(|e| e.to_string())?;

                    let log_path = shared_app_data.join("native-desktop-0.14.13.log");
                    let (engine_root, runtime_fingerprint) = extract_engine(&zip_path, &engine_root, &log_path)?;

                    let runtime_port = shared_app_data.join("runtime-port.txt");
                    let runtime_ready = shared_app_data.join("runtime-ready.txt");
                    let _ = fs::remove_file(&runtime_port);
                    let _ = fs::remove_file(&runtime_ready);

                    let stdout = fs::OpenOptions::new().create(true).append(true).open(&log_path)
                        .map_err(|e| format!("Cannot create startup log: {e}"))?;
                    let stderr = stdout.try_clone().map_err(|e| e.to_string())?;

                    let port = choose_free_port()?;
                    fs::write(&runtime_port, port.to_string()).map_err(|e| e.to_string())?;

                    let mut cmd = python_command()?;
                    cmd.arg(engine_root.join("run_modern_ui.py"))
                        .arg("--no-browser")
                        .arg("--host")
                        .arg("127.0.0.1")
                        .arg("--port")
                        .arg(port.to_string())
                        .arg("--repo-root")
                        .arg(&engine_root)
                        .arg("--app-data-dir")
                        .arg(&shared_app_data)
                        .env("STOCK_MODERN_UI_PREVIEW", "0")
                        .stdout(Stdio::from(stdout))
                        .stderr(Stdio::from(stderr));

                    let mut child = cmd
                        .spawn()
                        .map_err(|e| format!("Cannot start local engine: {e}"))?;
                    wait_for_server(&mut child, port, APP_VERSION, Duration::from_secs(45))?;

                    fs::write(&runtime_ready, format!("{APP_VERSION}\n{port}\n{runtime_fingerprint}\n"))
                        .map_err(|e| e.to_string())?;

                    *state_for_setup
                        .lock()
                        .map_err(|_| "Engine process lock poisoned")? = Some(child);

                    let url = format!("http://127.0.0.1:{port}/");
                    let parsed = url
                        .parse()
                        .map_err(|e| format!("Invalid local app URL: {e}"))?;
                    window
                        .navigate(parsed)
                        .map_err(|e| format!("Cannot open native workspace: {e}"))?;
                    window.show().map_err(|e| e.to_string())?;
                    window.set_focus().map_err(|e| e.to_string())?;
                    Ok(())
                })();

                if result.is_err() {
                    let _ = window.eval(
                        "window.__SRE_SHOW_ERROR__ && window.__SRE_SHOW_ERROR__('Startup failed. See local log for details.');"
                    );
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            });
            Ok(())
        })
        .on_window_event(move |_window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Ok(mut guard) = state_for_exit.lock() {
                    if let Some(child) = guard.as_mut() {
                        let _ = child.kill();
                    }
                    *guard = None;
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Stock Recommendation Engine");
}
