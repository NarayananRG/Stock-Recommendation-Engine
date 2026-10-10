#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    fs,
    io,
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

use tauri::Manager;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

const PORT: u16 = 18765;
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
    if destination.join(".sre091-ready").exists() {
        return Ok(destination.to_path_buf());
    }
    let parent = destination.parent().ok_or("No engine parent directory")?;
    fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    let staging = parent.join("engine-v091-staging");
    if staging.exists() { fs::remove_dir_all(&staging).map_err(|e| e.to_string())?; }
    fs::create_dir_all(&staging).map_err(|e| e.to_string())?;

    let file = fs::File::open(zip_path).map_err(|e| format!("Cannot open bundled engine source: {e}"))?;
    let mut archive = zip::ZipArchive::new(file).map_err(|e| format!("Invalid bundled engine source: {e}"))?;
    archive.extract(&staging).map_err(|e| format!("Cannot extract bundled engine source: {e}"))?;

    if !staging.join("run_modern_ui.py").exists() {
        return Err("Bundled engine source is missing run_modern_ui.py".into());
    }
    if destination.exists() { fs::remove_dir_all(destination).map_err(|e| e.to_string())?; }
    copy_dir_all(&staging, destination).map_err(|e| format!("Cannot install local engine files: {e}"))?;
    fs::write(destination.join(".sre091-ready"), b"0.9.1-native-desktop").map_err(|e| e.to_string())?;
    let _ = fs::remove_dir_all(staging);
    Ok(destination.to_path_buf())
}

fn wait_for_server(child: &mut Child, timeout: Duration) -> Result<(), String> {
    let started = Instant::now();
    let address = SocketAddr::from(([127, 0, 0, 1], PORT));
    while started.elapsed() < timeout {
        if let Ok(Some(status)) = child.try_wait() {
            return Err(format!("Local engine exited during startup ({status})."));
        }
        if TcpStream::connect_timeout(&address, Duration::from_millis(250)).is_ok() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(180));
    }
    Err("Local engine did not become ready within 45 seconds.".into())
}

fn python_command() -> Result<Command, String> {
    for candidate in ["python.exe", "python"] {
        let mut probe = Command::new(candidate);
        probe.arg("--version").stdout(Stdio::null()).stderr(Stdio::null());
        #[cfg(target_os = "windows")]
        probe.creation_flags(CREATE_NO_WINDOW);
        if probe.status().map(|s| s.success()).unwrap_or(false) {
            let mut cmd = Command::new(candidate);
            #[cfg(target_os = "windows")]
            cmd.creation_flags(CREATE_NO_WINDOW);
            return Ok(cmd);
        }
    }
    Err("Python was not found. Install Python 3.12+ and reopen the app.".into())
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
            let zip_path = resource_dir.join("resources").join("SRE091_ENGINE_SOURCE.zip");

            let local_base = std::env::var_os("LOCALAPPDATA")
                .map(PathBuf::from)
                .unwrap_or_else(|| app.path().app_local_data_dir().unwrap_or_else(|_| PathBuf::from(".")));
            let shared_app_data = local_base.join("StockRecommendationEngine");
            let engine_root = shared_app_data.join("native-engine-0.9.1");

            thread::spawn(move || {
                let result: Result<(), String> = (|| {
                    let engine_root = extract_engine(&zip_path, &engine_root)?;
                    fs::create_dir_all(&shared_app_data).map_err(|e| e.to_string())?;
                    let log_path = shared_app_data.join("native-desktop-0.9.1.log");
                    let stdout = fs::File::create(&log_path).map_err(|e| format!("Cannot create startup log: {e}"))?;
                    let stderr = stdout.try_clone().map_err(|e| e.to_string())?;

                    let mut cmd = python_command()?;
                    cmd.arg(engine_root.join("run_modern_ui.py"))
                        .arg("--no-browser")
                        .arg("--host").arg("127.0.0.1")
                        .arg("--port").arg(PORT.to_string())
                        .arg("--repo-root").arg(&engine_root)
                        .arg("--app-data-dir").arg(&shared_app_data)
                        .env("STOCK_MODERN_UI_PREVIEW", "1")
                        .stdout(Stdio::from(stdout))
                        .stderr(Stdio::from(stderr));
                    let mut child = cmd.spawn().map_err(|e| format!("Cannot start local engine: {e}"))?;
                    wait_for_server(&mut child, Duration::from_secs(45))?;
                    *state_for_setup.lock().map_err(|_| "Engine process lock poisoned")? = Some(child);

                    let url = format!("http://127.0.0.1:{PORT}/");
                    let parsed = url.parse().map_err(|e| format!("Invalid local app URL: {e}"))?;
                    window.navigate(parsed).map_err(|e| format!("Cannot open native workspace: {e}"))?;
                    window.show().map_err(|e| e.to_string())?;
                    window.set_focus().map_err(|e| e.to_string())?;
                    Ok(())
                })();

                if let Err(message) = result {
                    let safe = message.replace('\\', "\\\\").replace('`', "\\`").replace("${", "\\${");
                    let js = format!("window.__SRE_SHOW_ERROR__ && window.__SRE_SHOW_ERROR__(`{safe}`);");
                    let _ = window.eval(&js);
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            });
            Ok(())
        })
        .on_window_event(move |_window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Ok(mut guard) = state_for_exit.lock() {
                    if let Some(child) = guard.as_mut() { let _ = child.kill(); }
                    *guard = None;
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Stock Recommendation Engine");
}
