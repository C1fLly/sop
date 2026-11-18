"""拼任务包（设计书 9.1）：固定八节，只给路径不复制内容。另写一份 task.json 给机器读（范围、步骤、第几次、结果文件放哪）。"""
import json
import pathlib

from .project import TOOLKIT
from runner.placement import OUT_MNT

RESULT = f'{OUT_MNT}/result.json'
FORBID = ('不修改已有的测试来让测试通过', '不碰受保护路径（见 AGENTS.md）', '不做范围以外的事', '不推送、不开 PR、不建分支或工作目录')


def build(task_dir, *, scope, step, attempt, action, skill, must_read, allowed, done_when, fill, result_kind):
    task_dir = pathlib.Path(task_dir)
    task_dir.mkdir(parents=True, exist_ok=True)
    tmpl = (TOOLKIT / 'prompts' / f'{action}.md').read_text(encoding='utf-8')
    body = tmpl
    for k, v in fill.items():
        body = body.replace('{' + k + '}', str(v))
    md = [f'# 任务包：{step}（{scope}，第 {attempt} 次）', '', body.strip(), '',
          '## 技能', f'调用 `{skill}`。' if skill else '无。', '',
          '## 必读', *[f'- {p}' for p in must_read], '',
          '## 可改范围', *[f'- {p}' for p in allowed], '',
          '## 禁止', *[f'- {x}' for x in FORBID], '',
          '## 完成标准', *[f'- {x}' for x in done_when], '',
          '## 交回', f'结束时写一份 JSON 结果文件到 {RESULT}：status（done / partial / question）、commits、commands（cmd、rc）、'
          'deviations、questions（text、category：业务 或 技术）、findings（text、blocking）' + ('、pr_body' if result_kind == 'impl' else '') + '。', '',
          '## 不确定时', '不猜。把问题写进结果文件，标明是业务问题还是技术问题，然后正常结束。', '']
    (task_dir / 'task.md').write_text('\n'.join(md), encoding='utf-8')
    (task_dir / 'task.json').write_text(json.dumps({'scope': scope, 'step': step, 'attempt': attempt, 'result_path': RESULT,
                                                    'allowed': allowed, 'skill': skill, 'kind': result_kind}, ensure_ascii=False, indent=1))
    return task_dir
