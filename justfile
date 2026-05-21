# 让所有定义的变量导出到配方的环境中
set export
# 更安全的 shell 行为
set shell := ["sh","-c"]
set windows-shell := ["sh", "-c"]

# =====================
# 变量定义
# =====================

# Node 版本
NODE_VERSION := "v20.11.0"

# 根据操作系统判断 Node 下载地址和文件名
NODE_DIST_URL := if os() == "windows" { "https://nodejs.org/dist/" + NODE_VERSION + "/node-" + NODE_VERSION + "-win-x64.zip" } else { "https://nodejs.org/dist/" + NODE_VERSION + "/node-" + NODE_VERSION + "-linux-x64.tar.gz" }
NODE_BIN_NAME := if os() == "windows" { "node.exe" } else { "bin/node" }

SWC_PLATFORM := if os() == "windows" { "win32-x64-msvc" } else { "linux-x64-gnu" }
STRIP_IMG         := "1"
STRIP_SOURCE_MAPS := "1"
STRIP_TESTS       := "1"
VERBOSE           := "0"

# 定义构建和输出路径
DEPLOY_DIR := "build/deploy"
FE_DIR := "ui"

install:
    @echo "Installing all monorepo dependencies..."
    @bun install --frozen-lockfile

test:
    @echo "Running backend tests..."
    @uv run pytest
    @echo "Running frontend unit tests..."
    @(cd ui/ && bun install && bun run test)
    @echo "Running Playwright e2e tests..."
    @(cd ui/ && bun run test:e2e)

_build-ui:
    @echo "Building Frontend (Standalone)..."
    @(cd ui/ && bun install && bun run build)

assemble:
    @echo "Starting assembly of frontend application..."
    @rm -rf {{DEPLOY_DIR}}
    # 1. 创建 frontend 子目录 (对应 Python 代码中的 frontend_dir)
    @mkdir -p {{DEPLOY_DIR}}/frontend

    @echo "Copying application server code..."
    @cp -r {{FE_DIR}}/.next/standalone/* {{DEPLOY_DIR}}/frontend/
    @cp -r {{FE_DIR}}/.next/standalone/.next {{DEPLOY_DIR}}/frontend/

    @echo "Injecting static assets..."
    @mkdir -p {{DEPLOY_DIR}}/frontend/.next/static
    @cp -r {{FE_DIR}}/.next/static/* {{DEPLOY_DIR}}/frontend/.next/static/
    @cp -r {{FE_DIR}}/src/public {{DEPLOY_DIR}}/frontend/

    @echo "✅ Frontend assembled."

get-node:
    @echo "Downloading Node.js binary ({{NODE_VERSION}}) for {{os()}}..."
    @mkdir -p build/tmp_node

    # 1. 下载
    @curl -L -o build/node_dist.archive {{NODE_DIST_URL}}

    # 2. 解压并提取 (根据不同系统处理)
    @if [ "{{os()}}" = "windows" ]; then \
        echo "Extracting Windows binary..."; \
        unzip -q -o build/node_dist.archive -d build/tmp_node; \
        mv build/tmp_node/node-*/node.exe {{DEPLOY_DIR}}/; \
    else \
        echo "Extracting Linux binary..."; \
        tar -xzf build/node_dist.archive -C build/tmp_node; \
        mv build/tmp_node/node-*/bin/node {{DEPLOY_DIR}}/; \
    fi

    # 3. 清理
    @rm -rf build/tmp_node build/node_dist.archive
    @echo "✅ Node binary placed in {{DEPLOY_DIR}}"

prune:
    @echo "[prune] Pruning node_modules in {{DEPLOY_DIR}}..."
    @if [ ! -d {{DEPLOY_DIR}}/frontend/node_modules/next/dist/compiled ]; then \
        echo "[prune] Target directory not found. Run 'just assemble' first."; exit 1; \
    fi

    @echo "[prune] Keeping swc platform: $${SWC_PLATFORM}"
    @cd {{DEPLOY_DIR}}/frontend/node_modules/next/dist/compiled; \
    for d in @next/swc-*; do \
        if echo "$d" | grep -q "$$SWC_PLATFORM"; then \
            if [ "$VERBOSE" = "1" ]; then echo "  keep $$d"; fi; \
        else \
            echo "  remove $$d"; rm -rf "$$d"; \
        fi; \
    done

    @if [ "$STRIP_IMG" = "1" ]; then \
        echo "[prune] Removing @img"; \
        rm -rf {{DEPLOY_DIR}}/frontend/node_modules/@img || true; \
    fi

    @if [ "$STRIP_SOURCE_MAPS" = "1" ]; then \
        echo "[prune] Removing source maps (*.map)"; \
        find {{DEPLOY_DIR}} -name "*.map" -type f -delete || true; \
    fi

    @echo "[prune] Final size of deploy folder:"
    @du -sh {{DEPLOY_DIR}}

package:
    @echo "Compressing artifacts to 'build/static.tar.gz'..."
    @mkdir -p build
    @tar -czf build/runtime.tar.gz -C {{DEPLOY_DIR}} .
    @ls -lh build/runtime.tar.gz
    @echo "🚀 Ready for deployment!"

build-ui: _build-ui assemble get-node prune package
    @echo "🎉 Frontend application built, prepared, and packaged."

build-exe:
  pyinstaller dingent.spec

build: build-ui build-exe
    @echo "🎉 Full application built and packaged."
