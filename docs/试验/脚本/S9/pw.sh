# 在受限环境里执行：经专用 Docker，在固定的浏览器镜像里跑页面测试
cd apps/web
docker run --rm -e CI=true -v "$PWD":/work -w /work mcr.microsoft.com/playwright:v1.65.0-noble node node_modules/@playwright/test/cli.js test "$@" 2>&1 | tail -25
echo "容器退出码 ${PIPESTATUS[0]}"
