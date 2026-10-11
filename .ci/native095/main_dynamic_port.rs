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

const APP_VERSION: &str = "0.9.5-port-isolation";
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
    let ready = destination.join(".sre095-ready");
    if ready.exists() {
        return Ok(destination.to_path_buf());
    }
    let parent = destination.parent().ok_or("No engine parent directory")?;
    fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    let staging = parent.join("engine-v095-staging");
    if staging.exists() {
        fs::remove_dir_all(&staging).map_err(|e| e.to_string())?;
    }
    fs::create_dir_all(&staging).map_err(|e| e.to_string())?;

    let file = fs::File::open(zip_path).map_err(|e| format!("Cannot open bundled engine source: {e}"))?;
    let mut archive = zip::ZipArchive::new(file).map_err(|e| format!("Invalid bundled engine source: {e}"))?;
    archive.extract(&staging).map_err(|e| format!("Cannot extract bundled engine source: {e}"))?;

    let extracted = staging.join("engine-src");
    if !extracted.exists() {
        return Err("Bundled engine source did not contain engine-src".into());
    }
    if destination.exists() {
        fs::remove_dir_all(destination).map_err(|e| e.to_string())?;
    }
    copy_dir_all(&extracted, destination).map_err(|e| format!("Cannot install local engine files: {e}"))?;
    fs::write(&ready, APP_VERSION.as_bytes()).map_err(|e| e.to_string())?;
    let _ = fs::remove_dir_all(staging);
    Ok(destination.to_path_buf())
}

fn choose_free_port() -> Result<u16, String> {
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .map_err(|e| format!("Cannot allocate local port: {e}"))?;
    let port = listener.local_addr()
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
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
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

fn wait_for_server(child: &mut Child, port: u16, expected_version: &str, timeout: Duration) -> Result<(), String> {
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
    Err(format!("Local engine did not become ready with version {expected_version} within 30 seconds."))
}

fn main() {
    let child_state: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(None));
    let state_for_setup = child_state.clone();
    let state_for_exit = child_state.clone();

    tauri::Builder::default()
        .setup(move |app| {
            let window = app.get_webview_window("main")
                .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "Main window was not created"))?;
            let resource_dir = app.path().resource_dir()?;
            let zip_path = resource_dir.join("resources").join("SRE095_ENGINE_SOURCE.zip");
            let backend_path = resource_dir.join("binaries").join("sre_engine.exe");

            let local_base = std::env::var_os("LOCALAPPDATA")
                .map(PathBuf::from)
                .unwrap_or_else(|| app.path().app_local_data_dir().unwrap_or_else(|_| PathBuf::from(".")));
            let shared_app_data = local_base.join("StockRecommendationEngine");
            let engine_root = shared_app_data.join("native-engine-0.9.5");

            thread::spawn(move || {
                let result: Result<(), String> = (|| {
                    let engine_root = extract_engine(&zip_path, &engine_root)?;
                    if !backend_path.exists() {
                        return Err(format!("Bundled local engine executable is missing: {}", backend_path.display()));
                    }
                    fs::create_dir_all(&shared_app_data).map_err(|e| e.to_string())?;
                    let log_path = shared_app_data.join("native-desktop-0.9.5.log");
                    let stdout = fs::File::create(&log_path).map_err(|e| format!("Cannot create startup log: {e}"))?;
                    let stderr = stdout.try_clone().map_err(|e| e.to_string())?;

                    let port = choose_free_port()?;
                    let mut cmd = Command::new(&backend_path);
                    cmd.arg("--no-browser")
                        .arg("--host").arg("127.0.0.1")
                        .arg("--port").arg(port.to_string())
                        .arg("--repo-root").arg(&engine_root)
                        .arg("--app-data-dir").arg(&shared_app_data)
                        .env("STOCK_MODERN_UI_PREVIEW", "0")
                        .stdout(Stdio::from(stdout))
                        .stderr(Stdio::from(stderr));

                    #[cfg(target_os = "windows")]
                    cmd.creation_flags(CREATE_NO_WINDOW);

                    let mut child = cmd.spawn().map_err(|e| format!("Cannot start local engine: {e}"))?;
                    wait_for_server(&mut child, port, APP_VERSION, Duration::from_secs(30))?;
                    *state_for_setup.lock().map_err(|_| "Engine process lock poisoned")? = Some(child);

                    let url = format!("http://127.0.0.1:{port}/");
                    let parsed = url.parse().map_err(|e| format!("Invalid local app URL: {e}"))?;
                    window.navigate(parsed).map_err(|e| format!("Cannot open native workspace: {e}"))?;
                    window.show().map_err(|e| e.to_string())?;
                    window.set_focus().map_err(|e| e.to_string())?;
                    Ok(())
                })();

                if result.is_err() {
                    let _ = window.eval("window.__SRE_SHOW_ERROR__ && window.__SRE_SHOW_ERROR__('Startup failed. See local log for details.');");
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
