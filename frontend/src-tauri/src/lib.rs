// frontend/src-tauri/src/lib.rs
use chrono::Local;
use serde::Deserialize;
use std::error::Error;
use std::fs::{self, OpenOptions};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;
use tauri::{AppHandle, Manager};

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;


#[derive(Deserialize)]
struct RuntimeManifest {
    runtime_python: String,
}

// 用于存储后端进程句柄
struct BackendProcess(Mutex<Option<Child>>);

#[tauri::command]
fn get_backend_port() -> Result<u16, String> {
    let port_file = dirs::home_dir()
        .ok_or("Cannot find home directory")?
        .join(".owl_backend_port");

    // 等待最多 10 秒
    for _ in 0..100 {
        if port_file.exists() {
            let content = fs::read_to_string(&port_file)
                .map_err(|e| format!("Failed to read port file: {e}"))?;
            let port: u16 = content
                .trim()
                .parse()
                .map_err(|e| format!("Invalid port number: {e}"))?;
            return Ok(port);
        }
        thread::sleep(Duration::from_millis(100));
    }

    Err("Backend failed to start within 10 seconds".to_string())
}

#[tauri::command]
fn open_log_directory() -> Result<(), String> {
    let log_dir = dirs::home_dir()
        .ok_or("Cannot find home directory")?
        .join(".owl")
        .join("logs");

    if !log_dir.exists() {
        return Err("Log directory does not exist yet".to_string());
    }

    #[cfg(target_os = "windows")]
    Command::new("explorer")
        .arg(&log_dir)
        .spawn()
        .map_err(|e| format!("Failed to open log directory: {e}"))?;

    #[cfg(target_os = "macos")]
    Command::new("open")
        .arg(&log_dir)
        .spawn()
        .map_err(|e| format!("Failed to open log directory: {e}"))?;

    #[cfg(target_os = "linux")]
    Command::new("xdg-open")
        .arg(&log_dir)
        .spawn()
        .map_err(|e| format!("Failed to open log directory: {e}"))?;

    Ok(())
}

fn find_python_executable(python_env_dir: &PathBuf) -> Result<PathBuf, String> {
    // 优先读取 runtime_manifest.json
    let manifest_path = python_env_dir.join("runtime_manifest.json");
    if manifest_path.exists() {
        let manifest_content = fs::read_to_string(&manifest_path)
            .map_err(|e| format!("Failed to read runtime manifest: {e}"))?;
        let manifest: RuntimeManifest = serde_json::from_str(&manifest_content)
            .map_err(|e| format!("Failed to parse runtime manifest: {e}"))?;

        let python_exe = python_env_dir.join(&manifest.runtime_python);
        if python_exe.exists() {
            return Ok(python_exe);
        }
    }

    // Fallback: 根据平台猜测路径
    let candidates = if cfg!(target_os = "windows") {
        vec![
            python_env_dir.join("install").join("python.exe"),
            python_env_dir
                .join("python")
                .join("install")
                .join("python.exe"),
        ]
    } else {
        vec![
            python_env_dir.join("install").join("bin").join("python3"),
            python_env_dir
                .join("python")
                .join("install")
                .join("bin")
                .join("python3"),
        ]
    };

    for candidate in candidates {
        if candidate.exists() {
            return Ok(candidate);
        }
    }

    Err(format!(
        "Python executable not found in {}",
        python_env_dir.display()
    ))
}

// 智能查找 python_env 目录（开发/生产环境自适应）
fn find_python_env_dir(app: &tauri::App) -> Result<PathBuf, String> {
    println!("🔍 Searching for python_env directory...");

    // 策略 1: 生产环境 - resources 目录
    if let Ok(resource_dir) = app.path().resource_dir() {
        let prod_path = resource_dir.join("python_env");
        if prod_path.exists() && prod_path.join("sidecar_main.py").exists() {
            println!("📦 Found bundled python_env: {}", prod_path.display());
            return Ok(prod_path);
        }
    }

    // 策略 2: 开发环境 - 从当前可执行文件向上查找项目根目录
    if let Ok(current_exe) = std::env::current_exe() {
        // 从可执行文件路径向上遍历，查找包含 python_env 的目录
        for ancestor in current_exe.ancestors().skip(1) {
            let candidate = ancestor.join("python_env");
            if candidate.exists() && candidate.join("sidecar_main.py").exists() {
                println!("🔧 Found development python_env: {}", candidate.display());
                return Ok(candidate);
            }

            // 额外检查：如果找到了 frontend 目录，说明到了项目根目录附近
            if ancestor.join("frontend").exists() {
                let root_candidate = ancestor.join("python_env");
                if root_candidate.exists() && root_candidate.join("sidecar_main.py").exists() {
                    println!(
                        "🔧 Found python_env at project root: {}",
                        root_candidate.display()
                    );
                    return Ok(root_candidate);
                }
            }
        }
    }

    // 策略 3: 使用工作目录（最后的 fallback）
    if let Ok(current_dir) = std::env::current_dir() {
        // 尝试当前目录
        let candidate = current_dir.join("python_env");
        if candidate.exists() && candidate.join("sidecar_main.py").exists() {
            println!("🔧 Found python_env in current dir: {}", candidate.display());
            return Ok(candidate);
        }

        // 尝试上级目录（可能在 frontend 子目录中运行）
        if let Some(parent) = current_dir.parent() {
            let candidate = parent.join("python_env");
            if candidate.exists() && candidate.join("sidecar_main.py").exists() {
                println!("🔧 Found python_env in parent dir: {}", candidate.display());
                return Ok(candidate);
            }
        }
    }

    Err("python_env directory not found. Please run 'npm run build-sidecar' first.".to_string())
}

// 设置后端日志文件
fn setup_backend_logging() -> Result<(std::fs::File, std::fs::File), String> {
    // 创建日志目录
    let log_dir = dirs::home_dir()
        .ok_or("Cannot find home directory")?
        .join(".owl")
        .join("logs");

    fs::create_dir_all(&log_dir).map_err(|e| format!("Failed to create log directory: {e}"))?;

    // 创建日志文件（带时间戳）
    let timestamp = Local::now().format("%Y%m%d_%H%M%S");
    let stdout_log = log_dir.join(format!("backend_{}.log", timestamp));
    let stderr_log = log_dir.join(format!("backend_{}_error.log", timestamp));

    let stdout_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&stdout_log)
        .map_err(|e| format!("Failed to create stdout log: {e}"))?;

    let stderr_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&stderr_log)
        .map_err(|e| format!("Failed to create stderr log: {e}"))?;

    println!("📝 Backend logs will be saved to:");
    println!("   stdout: {}", stdout_log.display());
    println!("   stderr: {}", stderr_log.display());

    Ok((stdout_file, stderr_file))
}

// 清理后端进程的辅助函数
fn cleanup_backend(app_handle: &AppHandle) {
    if let Some(backend_state) = app_handle.try_state::<BackendProcess>() {
        if let Ok(mut backend_guard) = backend_state.0.lock() {
            if let Some(mut child) = backend_guard.take() {
                match child.kill() {
                    Ok(_) => println!("🦉 Backend process terminated successfully"),
                    Err(e) => eprintln!("⚠️  Failed to kill backend process: {e}"),
                }
                // 等待进程完全退出
                let _ = child.wait();
            }
        }
    }

    // 清理端口文件
    if let Some(home) = dirs::home_dir() {
        let port_file = home.join(".owl_backend_port");
        if port_file.exists() {
            let _ = fs::remove_file(&port_file);
            println!("🧹 Cleaned up port file");
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| -> Result<(), Box<dyn Error>> {
            // 使用智能查找逻辑
            let python_env_dir = find_python_env_dir(app)?;

            // 动态查找 Python 可执行文件
            let python_exe = find_python_executable(&python_env_dir)
                .map_err(|e| format!("Failed to find Python: {e}"))?;

            // 启动脚本是 sidecar_main.py
            let sidecar_script = python_env_dir.join("sidecar_main.py");

            if !sidecar_script.exists() {
                return Err(format!(
                    "sidecar_main.py not found at {}",
                    sidecar_script.display()
                )
                .into());
            }

            println!("🦉 Starting Owl backend...");
            println!("   Python: {}", python_exe.display());
            println!("   Script: {}", sidecar_script.display());

            // 统一使用文件日志
            let (stdout_file, stderr_file) = setup_backend_logging()?;
            
            // let child = Command::new(&python_exe)
            //     .current_dir(&python_env_dir)
            //     .arg("-u") // 强制 Python 输出不缓冲,实时写入日志
            //     .arg(&sidecar_script)
            //     .env("PYTHONUTF8", "1")      // 强制 UTF-8 模式（解决 Windows GBK 编码问题）
            //     .env("APP_MODE", "desktop")  // 设置应用模式
            //     .stdout(Stdio::from(stdout_file))
            //     .stderr(Stdio::from(stderr_file))
            //     .spawn()
            //     .map_err(|e| format!("Failed to start python backend: {e}"))?;

            let mut cmd = Command::new(&python_exe);
            cmd.current_dir(&python_env_dir)
                .arg("-u")
                .arg(&sidecar_script)
                .env("PYTHONUTF8", "1")
                .env("APP_MODE", "desktop")
                .stdout(Stdio::from(stdout_file))
                .stderr(Stdio::from(stderr_file));
            // Windows 下隐藏控制台窗口，避免用户误关
            #[cfg(target_os = "windows")]
            {
                const CREATE_NO_WINDOW: u32 = 0x08000000;
                cmd.creation_flags(CREATE_NO_WINDOW);
            }
            let child = cmd
                .spawn()
                .map_err(|e| format!("Failed to start python backend: {e}"))?;


            println!("🦉 Backend process started with PID: {}", child.id());

            // 将进程句柄存储到应用状态
            app.manage(BackendProcess(Mutex::new(Some(child))));

            Ok(())
        })
        .on_window_event(|window, event| {
            // 当窗口关闭时，清理后端进程
            match event {
                tauri::WindowEvent::CloseRequested { .. } | tauri::WindowEvent::Destroyed => {
                    println!("🦉 Window closing, cleaning up backend...");
                    cleanup_backend(window.app_handle());
                }
                _ => {}
            }
        })
        .invoke_handler(tauri::generate_handler![get_backend_port, open_log_directory])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}