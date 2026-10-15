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

use tauri::Manager;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

const APP_VERSION: &str = "0.14.6-official-data-refresh-repair";
const CREATE_NO_WINDOW: u32 = 0x08000000;

fn copy_dir_all(src: impl AsRef<Path>, dst: impl AsRef<Path>) -> io::Result<()> {
    let src = src.as_ref();
    let dst = dst.as_ref();
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let ty = entry.file_type()?;
        let from = entry.path();
        let to = dst.join(entry.file_name());
        if ty.is_dir() {
            copy_dir_all(&from, &to)?;
        } else {
            fs::copy(&from, &to)?;
        }
    }
    Ok(())
}
fn extract_engine(zip_path: &Path, destination: &Path) -> Result<PathBuf, String> {
    if destination.join(".sre0146-ready").exists() {
        return Ok(destination.to_path_buf());
    }
    let parent = destination.parent().ok_or("No engine parent directory")?;
    fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    let staging = parent.join("engine-v0146-staging");
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
    if destination.exists() {
        fs::remove_dir_all(destination).map_err(|e| e.to_string())?;
    }
    copy_dir_all(&staging, destination)
        .map_err(|e| format!("Cannot install local engine files: {e}"))?;
    fs::write(destination.join(".sre0146-ready"), APP_VERSION.as_bytes())
        .map_err(|e| e.to_string())?;
    let _ = fs::remove_dir_all(staging);
    Ok(destination.to_path_buf())
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
                .join("SRE0146_ENGINE_SOURCE.zip");

            let local_base = std::env::var_os("LOCALAPPDATA")
                .map(PathBuf::from)
                .unwrap_or_else(|| {
                    app.path()
                        .app_local_data_dir()
                        .unwrap_or_else(|_| PathBuf::from("."))
                });
            let shared_app_data = local_base.join("StockRecommendationEngine");
            let engine_root = shared_app_data.join("native-engine-0.14.6");

            thread::spawn(move || {
                let result: Result<(), String> = (|| {
                    let engine_root = extract_engine(&zip_path, &engine_root)?;
                    fs::create_dir_all(&shared_app_data).map_err(|e| e.to_string())?;

                    let runtime_port = shared_app_data.join("runtime-port.txt");
                    let runtime_ready = shared_app_data.join("runtime-ready.txt");
                    let _ = fs::remove_file(&runtime_port);
                    let _ = fs::remove_file(&runtime_ready);

                    let log_path = shared_app_data.join("native-desktop-0.14.6.log");
                    let stdout = fs::File::create(&log_path)
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

                    fs::write(&runtime_ready, format!("{APP_VERSION}\n{port}\n"))
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
