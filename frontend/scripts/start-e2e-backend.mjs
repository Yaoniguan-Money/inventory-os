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

const checkScript = [
  'import asyncio',
  'from sqlalchemy import select',
  'from app.core.database import new_session',
  'from app.domains.identity.models import User, Organization',
  'from app.core.security import verify_password',
  'from app.core.config import settings',
  'async def main():',
  '    async with new_session() as db:',
  '        users = (await db.execute(select(User))).scalars().all()',
  '        orgs = (await db.execute(select(Organization))).scalars().all()',
  '        print("SEED_CHECK users=", len(users), "orgs=", len(orgs))',
  '        for u in users:',
  '            print("SEED_CHECK user=", u.email, "password_ok=", verify_password(settings.demo_admin_password, u.password_hash))',
  'asyncio.run(main())',
].join('\n')
const check = spawnSync('uv', ['run', 'python', '-'], {
  cwd: backendDir,
  stdio: ['pipe', 'inherit', 'inherit'],
  shell,
  input: checkScript,
})
if (check.status !== 0) {
  process.exit(check.status ?? 1)
}

const server = spawn(
  'uv',
  ['run', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'],
  { cwd: backendDir, stdio: 'inherit', shell },
)
server.on('exit', (code) => process.exit(code ?? 0))
