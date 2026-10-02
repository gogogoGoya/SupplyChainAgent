import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const projectRootDir = path.resolve(__dirname, '..')
const agentDir = path.resolve(projectRootDir, 'agent')
const workspaceMultiDir = path.resolve(agentDir, 'workspace_multi')
const simulationRunsDir = path.resolve(agentDir, 'simulation_runs')
const workspaceJobsDir = path.resolve(agentDir, 'workspace_jobs')
const operationsApiTarget = process.env.OPERATIONS_API_PROXY_TARGET || 'http://127.0.0.1:8000'

const contentTypes = {
  '.json': 'application/json; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8'
}

function serveDirectory(urlPrefix, rootDir) {
  const serve = (middlewares) => {
    middlewares.use(urlPrefix, (req, res, next) => {
      const requestPath = decodeURIComponent((req.url || '/').split('?')[0])
      const filePath = path.normalize(path.join(rootDir, requestPath))

      if (!filePath.startsWith(rootDir)) {
        res.statusCode = 403
        res.end('Forbidden')
        return
      }

      if (!fs.existsSync(filePath)) {
        res.statusCode = 404
        res.end('Not Found')
        return
      }

      const stat = fs.statSync(filePath)
      if (stat.isDirectory()) {
        const entries = fs.readdirSync(filePath, { withFileTypes: true }).reduce((acc, entry) => {
          acc[entry.name] = entry.isDirectory() ? 'directory' : 'file'
          return acc
        }, {})
        res.setHeader('Content-Type', 'application/json; charset=utf-8')
        res.end(JSON.stringify(entries))
        return
      }

      res.setHeader('Content-Type', contentTypes[path.extname(filePath)] || 'application/octet-stream')
      fs.createReadStream(filePath).pipe(res)
    })
  }

  return {
    name: `serve-${urlPrefix.replace(/\W+/g, '-')}`,
    configureServer(server) {
      serve(server.middlewares)
    },
    configurePreviewServer(server) {
      serve(server.middlewares)
    }
  }
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    serveDirectory('/workspace_multi', workspaceMultiDir),
    serveDirectory('/simulation_runs', simulationRunsDir),
    serveDirectory('/workspace_jobs', workspaceJobsDir)
  ],
  server: {
    host: '0.0.0.0',
    port: 3000,
    // The workspace contains hundreds of thousands of generated artifacts and
    // may exhaust the host's inotify quota before Vite starts. Polling keeps
    // hot reload available without allocating additional inotify watchers.
    watch: {
      usePolling: true,
      interval: 500
    },
    proxy: {
      '/operations': {
        target: operationsApiTarget,
        changeOrigin: true
      }
    }
  }
})
