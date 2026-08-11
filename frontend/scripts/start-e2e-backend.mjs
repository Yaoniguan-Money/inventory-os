import { spawn, spawnSync } from 'node:child_process'
import process from 'node:process'

// 跨平台 E2E 后端启动器：设置 DATABASE_URL → 重建并 seed → 启动 uvicorn。
const databaseUrl =
  process.env.E2E_DATABASE_URL ??
  'postgresql+asyncpg://inventory:inventory_dev_password@localhost:5433/inventory_os_e2e'
process.env.DATABASE_URL = databaseUrl

const backendDir = process.env.BACKEND_DIR ?? '../backend'
const shell = process.platform === 'win32'

const reset = spawnSync(
  'uv',
  ['run', 'python', '-m', 'app.scripts.reset_e2e'],
  { cwd: backendDir, stdio: 'inherit', shell },
)
if (reset.status !== 0) {
  process.exit(reset.status ?? 1)
}

const server = spawn(
  'uv',
  ['run', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'],
  { cwd: backendDir, stdio: 'inherit', shell },
)
server.on('exit', (code) => process.exit(code ?? 0))
