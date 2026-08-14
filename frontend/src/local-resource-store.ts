type PermissionMode = "read" | "readwrite"
type PermissionStateValue = "granted" | "denied" | "prompt"

type BrowserFileHandleLike = {
  getFile(): Promise<File>
  createWritable(): Promise<{
    write(data: Blob | Uint8Array): Promise<void>
    close(): Promise<void>
    abort?(): Promise<void>
  }>
}

type BrowserDirectoryHandleLike = {
  name: string
  getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<BrowserDirectoryHandleLike>
  getFileHandle(name: string, options?: { create?: boolean }): Promise<BrowserFileHandleLike>
  queryPermission(options: { mode: PermissionMode }): Promise<PermissionStateValue>
  requestPermission(options: { mode: PermissionMode }): Promise<PermissionStateValue>
}

type TauriDirectoryHandle = {
  kind: "tauri"
  name: string
  userId: string
}

export type DirectoryHandleLike = BrowserDirectoryHandleLike | TauriDirectoryHandle

type LocalResourceRecord = {
  id: string
  userId: string
  jobId: string
  outputIndex: number
  generationItemId?: string
  resourceKey: string
  directories: string[]
  filename: string
  savedAt: string
  desktopRelativePath?: string
}

const DATABASE_NAME = "zly-ai-video-studio-local-resources-v1"
const LEGACY_DATABASE_NAME = ["toon", "flow-local-resources-v1"].join("")
const DATABASE_VERSION = 1
const RESOURCE_DIRECTORY = "ZLY AI Studio"
const MIGRATION_MARKER = "migration:zly-ai-video-studio-v1"

type DatabaseInfo = { name?: string }
type IndexedDbWithDatabaseList = IDBFactory & { databases?: () => Promise<DatabaseInfo[]> }

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION)
    request.onupgradeneeded = () => {
      const database = request.result
      if (!database.objectStoreNames.contains("settings")) database.createObjectStore("settings")
      if (!database.objectStoreNames.contains("resources")) database.createObjectStore("resources", { keyPath: "id" })
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function transactionComplete(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve()
    transaction.onerror = () => reject(transaction.error)
    transaction.onabort = () => reject(transaction.error)
  })
}

async function legacyDatabaseExists(): Promise<boolean> {
  const indexedDb = indexedDB as IndexedDbWithDatabaseList
  const databaseList = indexedDb.databases
  if (!databaseList) return false
  return (await databaseList.call(indexedDb)).some((database) => database.name === LEGACY_DATABASE_NAME)
}

async function migrateLegacyDatabase(): Promise<void> {
  if (!(await legacyDatabaseExists())) return
  const database = await openDatabase()
  const markerTransaction = database.transaction("settings", "readonly")
  const migrated = await requestResult(markerTransaction.objectStore("settings").get(MIGRATION_MARKER))
  await transactionComplete(markerTransaction)
  if (migrated) {
    database.close()
    return
  }

  const legacyDatabase = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(LEGACY_DATABASE_NAME)
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
  const legacyTransaction = legacyDatabase.transaction(["settings", "resources"], "readonly")
  const settings = legacyTransaction.objectStore("settings")
  const resources = legacyTransaction.objectStore("resources")
  const [settingKeys, settingValues, resourceValues] = await Promise.all([
    requestResult(settings.getAllKeys()),
    requestResult(settings.getAll()),
    requestResult(resources.getAll()),
  ])
  await transactionComplete(legacyTransaction)
  legacyDatabase.close()

  const targetTransaction = database.transaction(["settings", "resources"], "readwrite")
  const targetSettings = targetTransaction.objectStore("settings")
  const targetResources = targetTransaction.objectStore("resources")
  settingKeys.forEach((key, index) => targetSettings.put(settingValues[index], key))
  resourceValues.forEach((resource) => targetResources.put(resource))
  targetSettings.put(true, MIGRATION_MARKER)
  await transactionComplete(targetTransaction)
  database.close()
}

let legacyMigration: Promise<void> | undefined

function ensureLegacyMigration(): Promise<void> {
  legacyMigration ??= migrateLegacyDatabase()
  return legacyMigration
}

async function readStore<T>(storeName: string, key: IDBValidKey): Promise<T | undefined> {
  await ensureLegacyMigration()
  const database = await openDatabase()
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(storeName, "readonly")
    const request = transaction.objectStore(storeName).get(key)
    request.onsuccess = () => resolve(request.result as T | undefined)
    request.onerror = () => reject(request.error)
    transaction.oncomplete = () => database.close()
  })
}

async function writeStore(storeName: string, value: unknown, key?: IDBValidKey): Promise<void> {
  await ensureLegacyMigration()
  const database = await openDatabase()
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(storeName, "readwrite")
    const store = transaction.objectStore(storeName)
    key === undefined ? store.put(value) : store.put(value, key)
    transaction.oncomplete = () => { database.close(); resolve() }
    transaction.onerror = () => reject(transaction.error)
  })
}

type TauriWindow = Window & { __TAURI_INTERNALS__?: unknown }

type DesktopDirectory = { name: string }
type DesktopSavedResource = { relativePath: string }
type DesktopDeliveryTicket = { download_url: string }
type BrowserDirectOutput = { view_url: string }

const isTauriDesktop = () => Boolean((window as TauriWindow).__TAURI_INTERNALS__)
const isTauriDirectory = (handle: DirectoryHandleLike): handle is TauriDirectoryHandle => "kind" in handle && handle.kind === "tauri"

async function desktopInvoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  if (!isTauriDesktop()) throw new Error("当前不是 ZLY AI Video Studio 桌面客户端")
  const { invoke } = await import("@tauri-apps/api/core")
  return invoke<T>(command, args)
}

export const directoryApiSupported = () => (
  isTauriDesktop() || (window.isSecureContext && "showDirectoryPicker" in window && typeof indexedDB !== "undefined")
)

export async function chooseResourceDirectory(userId: string): Promise<DirectoryHandleLike> {
  if (isTauriDesktop()) {
    const directory = await desktopInvoke<DesktopDirectory | null>("desktop_choose_resource_directory", { userId })
    if (!directory) throw new DOMException("用户取消了目录选择", "AbortError")
    return { kind: "tauri", name: directory.name, userId }
  }
  const picker = (window as Window & { showDirectoryPicker?: (options?: { mode?: PermissionMode }) => Promise<DirectoryHandleLike> }).showDirectoryPicker
  if (!picker) throw new Error("当前浏览器不支持本地目录授权")
  const handle = await picker({ mode: "readwrite" }) as BrowserDirectoryHandleLike
  await writeStore("settings", handle, `directory:${userId}`)
  return handle
}

export async function getResourceDirectory(userId: string): Promise<DirectoryHandleLike | undefined> {
  if (isTauriDesktop()) {
    const configured = await desktopInvoke<boolean>("desktop_directory_configured", { userId })
    return configured ? { kind: "tauri", name: "员工电脑本地目录", userId } : undefined
  }
  return readStore<BrowserDirectoryHandleLike>("settings", `directory:${userId}`)
}

export async function directoryPermission(handle: DirectoryHandleLike, request = false): Promise<PermissionStateValue> {
  if (isTauriDirectory(handle)) {
    const configured = await desktopInvoke<boolean>("desktop_directory_configured", { userId: handle.userId })
    return configured ? "granted" : "denied"
  }
  const current = await handle.queryPermission({ mode: "readwrite" })
  if (current === "granted" || !request) return current
  return handle.requestPermission({ mode: "readwrite" })
}

async function responseForBrowserDelivery(
  jobId: string,
  outputIndex: number,
  downloadUrl: string,
  generationItemId?: string,
): Promise<Response> {
  try {
    const base = generationItemId
      ? `/api/jobs/${jobId}/generations/${generationItemId}/outputs/${outputIndex}`
      : `/api/jobs/${jobId}/outputs/${outputIndex}`
    const locator = await fetch(`${base}/browser-direct`)
    if (locator.ok) {
      const { view_url: viewUrl } = await locator.json() as BrowserDirectOutput
      const localResponse = await fetch(viewUrl, { redirect: "error" })
      if (localResponse.ok && localResponse.body) return localResponse
    }
  } catch {
    // A non-ComfyUI computer or CORS-blocked loopback response falls back below.
  }

  const response = await fetch(downloadUrl)
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || "Download failed")
  return response
}

async function writeResponseToFile(response: Response, fileHandle: BrowserFileHandleLike): Promise<void> {
  const writable = await fileHandle.createWritable()
  try {
    if (!response.body) {
      await writable.write(await response.blob())
    } else {
      const reader = response.body.getReader()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        await writable.write(value)
      }
    }
    await writable.close()
  } catch (error) {
    await writable.abort?.()
    throw error
  }
}

export async function saveToResourceDirectory(
  handle: DirectoryHandleLike,
  userId: string,
  jobId: string,
  outputIndex: number,
  resourceKey: string,
  downloadUrl: string,
  csrfToken?: string,
  generationItemId?: string,
): Promise<LocalResourceRecord> {
  const outputBase = generationItemId
    ? `/api/jobs/${jobId}/generations/${generationItemId}/outputs/${outputIndex}`
    : `/api/jobs/${jobId}/outputs/${outputIndex}`
  if (isTauriDirectory(handle)) {
    const ticketResponse = await fetch(`${outputBase}/desktop-ticket`, {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken ?? "" },
    })
    if (!ticketResponse.ok) throw new Error((await ticketResponse.json().catch(() => null))?.detail || "获取桌面下载凭证失败")
    const ticket = await ticketResponse.json() as DesktopDeliveryTicket
    const saved = await desktopInvoke<DesktopSavedResource>("desktop_save_resource", {
      userId,
      resourceKey,
      downloadUrl: ticket.download_url,
    })
    const record: LocalResourceRecord = {
      id: `${userId}:${resourceKey}`,
      userId,
      jobId,
      outputIndex,
      generationItemId,
      resourceKey,
      directories: [],
      filename: resourceKey,
      savedAt: new Date().toISOString(),
      desktopRelativePath: saved.relativePath,
    }
    await writeStore("resources", record)
    return record
  }
  if (await directoryPermission(handle) !== "granted") throw new Error("本地资源目录需要重新授权")
  const response = await responseForBrowserDelivery(jobId, outputIndex, downloadUrl, generationItemId)
  const month = new Date().toISOString().slice(0, 7)
  const base = await handle.getDirectoryHandle(RESOURCE_DIRECTORY, { create: true })
  const monthDirectory = await base.getDirectoryHandle(month, { create: true })
  const fileHandle = await monthDirectory.getFileHandle(resourceKey, { create: true })
  await writeResponseToFile(response, fileHandle)
  const record: LocalResourceRecord = {
    id: `${userId}:${resourceKey}`,
    userId,
    jobId,
    outputIndex,
    generationItemId,
    resourceKey,
    directories: [RESOURCE_DIRECTORY, month],
    filename: resourceKey,
    savedAt: new Date().toISOString(),
  }
  await writeStore("resources", record)
  return record
}

export async function localResourceUrl(
  handle: DirectoryHandleLike,
  userId: string,
  resourceKey: string,
): Promise<string | undefined> {
  const record = await readStore<LocalResourceRecord>("resources", `${userId}:${resourceKey}`)
  if (!record || await directoryPermission(handle) !== "granted") return undefined
  if (isTauriDirectory(handle)) {
    if (!record.desktopRelativePath) return undefined
    const path = await desktopInvoke<string | null>("desktop_local_resource_path", {
      userId,
      relativePath: record.desktopRelativePath,
    })
    if (!path) return undefined
    const { convertFileSrc } = await import("@tauri-apps/api/core")
    return convertFileSrc(path)
  }
  try {
    let directory = handle
    for (const name of record.directories) directory = await directory.getDirectoryHandle(name)
    const fileHandle = await directory.getFileHandle(record.filename)
    return URL.createObjectURL(await fileHandle.getFile())
  } catch {
    return undefined
  }
}

export async function localResourceFile(
  handle: DirectoryHandleLike,
  userId: string,
  resourceKey: string,
): Promise<File | undefined> {
  const record = await readStore<LocalResourceRecord>("resources", `${userId}:${resourceKey}`)
  if (!record || await directoryPermission(handle) !== "granted") return undefined
  if (isTauriDirectory(handle)) {
    const url = await localResourceUrl(handle, userId, resourceKey)
    if (!url) return undefined
    const response = await fetch(url)
    if (!response.ok) return undefined
    return new File([await response.blob()], record.filename, { type: response.headers.get("Content-Type") || "image/png" })
  }
  try {
    let directory = handle
    for (const name of record.directories) directory = await directory.getDirectoryHandle(name)
    return await (await directory.getFileHandle(record.filename)).getFile()
  } catch {
    return undefined
  }
}
