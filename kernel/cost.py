"""花费（设计书 8.4）：不设上限，只记录和展示；到一定数时提醒一次，不中断。

默认两个数：一个功能累计超过 50 美元提醒一次；整个项目每多花 200 美元提醒一次。用户随时可以改（~/tools/sop/config/cost.json）。
用的是工具报告的金额，不是服务后台实际扣的钱，提醒里写明这一点。
"""
import json
import shutil
import subprocess

from . import paths

DEFAULTS = {'feature_usd': 50.0, 'project_every_usd': 200.0}


def limits():
    f = paths.config_dir() / 'cost.json'
    return {**DEFAULTS, **(json.loads(f.read_text()) if f.exists() else {})}


def total(events):
    return round(sum(float(e.get('cost') or 0) for e in events if e.get('type') != 'note'), 4)


def alerts_due(feature, feature_events, all_events):
    """返回要发的提醒（记录事件的内容）。已经提醒过的不再提醒。"""
    lim = limits()
    sent = [e for e in all_events if e.get('type') == 'note' and e.get('kind') == '花费提醒']
    out = []
    ft = total(feature_events)
    if ft > lim['feature_usd'] and not any(e.get('what') == 'feature' and e.get('feature') == feature for e in sent):
        out.append({'kind': '花费提醒', 'what': 'feature', 'feature': feature, 'usd': ft,
                    'text': f'功能 {feature} 的 AI 花费已经累计 {ft:.2f} 美元，超过了 {lim["feature_usd"]:.0f} 美元（工具报告的金额，不是服务后台实际扣的钱）。流程照常往下走。'})
    pt = total(all_events)
    step = int(pt // lim['project_every_usd'])
    done = max([e.get('step', 0) for e in sent if e.get('what') == 'project'] or [0])
    if step > done:
        out.append({'kind': '花费提醒', 'what': 'project', 'step': step, 'usd': pt,
                    'text': f'整个项目的 AI 花费已经累计 {pt:.2f} 美元，又多了 {lim["project_every_usd"]:.0f} 美元（工具报告的金额）。流程照常往下走。'})
    return out


def notify(text):
    """桌面通知（7.12）。没有通知工具或在自测里时不发。"""
    import os
    if os.environ.get('SOP_NO_NOTIFY') or not shutil.which('notify-send'):
        return
    subprocess.run(['notify-send', 'SOP', text], capture_output=True)
