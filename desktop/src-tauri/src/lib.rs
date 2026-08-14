use chrono::Local;
use rfd::AsyncFileDialog;
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    fs,
    io::Write,
    path::{Component, Path, PathBuf},
    sync::Mutex,
};
use tauri::{AppHandle, Manager, State};

const WORKBENCH_URL: &str = "https://comfyui.zlyun168.com/";
const SETTINGS_FILE: &str = "delivery-directories.json";

#[derive(Default)]
struct DesktopState {
    directories: Mutex<BTreeMap<String, PathBuf>>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopDirectory {
    name: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SavedResource {
    relative_path: String,
}

#[derive(Serialize, Deserialize, Default)]
struct PersistedDirectories {
    directories: BTreeMap<String, PathBuf>,
}

fn settings_path(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(app
        .path()
        .app_local_data_dir()
        .map_err(|error| error.to_string())?
        .join(SETTINGS_FILE))
}

fn load_directories(app: &AppHandle) -> BTreeMap<String, PathBuf> {
    let Ok(path) = settings_path(app) else {
        return BTreeMap::new();
    };
    fs::read(path)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<PersistedDirectories>(&bytes).ok())
        .map(|settings| settings.directories)
        .unwrap_or_default()
}

fn persist_directories(
    app: &AppHandle,
    directories: &BTreeMap<String, PathBuf>,
) -> Result<(), String> {
    let path = settings_path(app)?;
    let parent = path.parent().ok_or("客户端配置目录无效")?;
    fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    let data = serde_json::to_vec_pretty(&PersistedDirectories {
        directories: directories.clone(),
    })
    .map_err(|error| error.to_string())?;
    fs::write(path, data).map_err(|error| error.to_string())
}

fn configured_directory(state: &DesktopState, user_id: &str) -> Option<PathBuf> {
    state
        .directories
        .lock()
        .ok()?
        .get(user_id)
        .filter(|path| path.is_dir())
        .cloned()
}

fn safe_relative_path(relative_path: &str) -> Option<PathBuf> {
    let path = Path::new(relative_path);
    if path.is_absolute()
        || path
            .components()
            .any(|component| !matches!(component, Component::Normal(_)))
    {
        return None;
    }
    Some(path.to_path_buf())
}

fn resource_target(
    state: &DesktopState,
    user_id: &str,
    resource_key: &str,
) -> Result<(PathBuf, PathBuf), String> {
    let filename = Path::new(resource_key);
    if resource_key.is_empty()
        || filename.components().count() != 1
        || filename
            .file_name()
            .and_then(|value| value.to_str())
            .is_none()
    {
        return Err("资源文件名无效".to_string());
    }
    let root = configured_directory(state, user_id).ok_or("请先选择作品存储目录")?;
    let month = Local::now().format("%Y-%m").to_string();
    let relative_path = PathBuf::from("ZLY AI Studio").join(month).join(filename);
    Ok((root.join(relative_path.clone()), relative_path))
}

fn desktop_download_url(download_url: &str) -> Result<reqwest::Url, String> {
    let workbench = reqwest::Url::parse(WORKBENCH_URL).map_err(|error| error.to_string())?;
    let url = workbench
        .join(download_url)
        .map_err(|error| error.to_string())?;
    if url.origin() != workbench.origin()
        || !url.path().starts_with("/api/jobs/")
        || !url
            .query_pairs()
            .any(|(name, value)| name == "desktop_ticket" && !value.is_empty())
    {
        return Err("桌面下载地址不受信任".to_string());
    }
    Ok(url)
}

#[tauri::command]
fn desktop_workbench_url() -> String {
    WORKBENCH_URL.to_string()
}

#[tauri::command]
fn desktop_directory_configured(user_id: String, state: State<'_, DesktopState>) -> bool {
    configured_directory(&state, &user_id).is_some()
}

#[tauri::command]
async fn desktop_choose_resource_directory(
    user_id: String,
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<Option<DesktopDirectory>, String> {
    let Some(selected) = AsyncFileDialog::new()
        .set_title("选择 ZLY AI 视频作品存储目录")
        .pick_folder()
        .await
    else {
        return Ok(None);
    };

    let directory = selected
        .path()
        .canonicalize()
        .map_err(|error| error.to_string())?;
    let name = directory
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("员工电脑本地目录")
        .to_string();
    let mut directories = state
        .directories
        .lock()
        .map_err(|_| "客户端目录状态不可用")?;
    directories.insert(user_id, directory);
    persist_directories(&app, &directories)?;
    Ok(Some(DesktopDirectory { name }))
}

#[tauri::command]
async fn desktop_save_resource(
    user_id: String,
    resource_key: String,
    download_url: String,
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<SavedResource, String> {
    let (target, relative_path) = resource_target(&state, &user_id, &resource_key)?;
    if target.exists() {
        return Err("本地已存在同名作品，请更换资源目录后重试".to_string());
    }
    let parent = target.parent().ok_or("目标目录无效")?;
    fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    let temporary = parent.join(format!(".{resource_key}.downloading"));
    let mut response = reqwest::Client::new()
        .get(desktop_download_url(&download_url)?)
        .send()
        .await
        .map_err(|error| format!("下载生成资源失败：{error}"))?;
    if !response.status().is_success() {
        return Err(format!("下载生成资源失败：HTTP {}", response.status()));
    }
    let mut file = fs::File::create(&temporary).map_err(|error| error.to_string())?;
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|error| format!("下载生成资源失败：{error}"))?
    {
        if let Err(error) = file.write_all(&chunk) {
            drop(file);
            let _ = fs::remove_file(&temporary);
            return Err(error.to_string());
        }
    }
    if let Err(error) = file.flush() {
        drop(file);
        let _ = fs::remove_file(&temporary);
        return Err(error.to_string());
    }
    drop(file);
    fs::rename(&temporary, &target).map_err(|error| error.to_string())?;
    app.asset_protocol_scope()
        .allow_file(&target)
        .map_err(|error| error.to_string())?;
    Ok(SavedResource {
        relative_path: relative_path.to_string_lossy().replace('\\', "/"),
    })
}

#[cfg(test)]
mod tests {
    use super::safe_relative_path;

    #[test]
    fn only_allows_normal_relative_paths() {
        assert_eq!(
            safe_relative_path("ZLY AI Studio/2026-08/result.mp4").is_some(),
            true
        );
        assert_eq!(safe_relative_path("../result.mp4"), None);
        assert_eq!(safe_relative_path("C:/result.mp4"), None);
        assert_eq!(safe_relative_path("/result.mp4"), None);
    }
}

#[tauri::command]
fn desktop_local_resource_path(
    user_id: String,
    relative_path: String,
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<Option<String>, String> {
    let Some(relative_path) = safe_relative_path(&relative_path) else {
        return Ok(None);
    };
    let Some(root) = configured_directory(&state, &user_id) else {
        return Ok(None);
    };
    let target = root.join(relative_path);
    if !target.is_file() {
        return Ok(None);
    }
    app.asset_protocol_scope()
        .allow_file(&target)
        .map_err(|error| error.to_string())?;
    Ok(Some(target.to_string_lossy().to_string()))
}

pub fn run() {
    tauri::Builder::default()
        .manage(DesktopState {
            directories: Mutex::new(BTreeMap::new()),
        })
        .setup(|app| {
            let state = app.state::<DesktopState>();
            let mut directories = state
                .directories
                .lock()
                .map_err(|_| "客户端目录状态不可用")?;
            *directories = load_directories(app.handle());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            desktop_workbench_url,
            desktop_directory_configured,
            desktop_choose_resource_directory,
            desktop_save_resource,
            desktop_local_resource_path,
        ])
        .run(tauri::generate_context!())
        .expect("启动 ZLYUN AI 失败");
}
