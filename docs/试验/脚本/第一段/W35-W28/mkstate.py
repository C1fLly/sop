#!/usr/bin/env python3
"""第一段 W35/W28：从模板现建一个 Claude Code 的状态目录。用法：mkstate.py <新目录> <工作目录> <claude 版本>
模板只含必需的设置：首次启动的引导已做过、这个工作目录已信任、「不逐条询问」模式的警告已接受、不自动升级。"""
import json, os, sys, pathlib
d, wd, ver = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path(d); assert not p.exists(), '状态目录必须是新建的'
p.mkdir(parents=True)
cfg = {'hasCompletedOnboarding': True, 'lastOnboardingVersion': ver, 'autoUpdates': False, 'bypassPermissionsModeAccepted': True,
       'projects': {wd: {'hasTrustDialogAccepted': True}}}
(p / '.claude.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=1)); os.chmod(p / '.claude.json', 0o600)
print('已从模板现建', d)
