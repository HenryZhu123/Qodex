import json
import re

# Compare system prompts in training data with current prompt files
# Also check if the error_type values in system prompts match the current prompt files

# First, let's get the distinct system prompts from training data
system_prompts = {}

with open(r'C:\hyt-agent\训练集-微调版提示词\train_v1.1\train_v1.1.jsonl', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        d = json.loads(line)
        messages = d['messages']
        system_msg = ''
        for m in messages:
            if m['role'] == 'system':
                system_msg = m['content']
                break

        # Extract the task name (line starting with "# 任务：")
        task_match = re.search(r'# 任务：(.+?)$', system_msg, re.MULTILINE)
        task_name = task_match.group(1).strip() if task_match else 'UNKNOWN'

        # Extract fixed error_type
        et_match = re.search(r'error_type.*固定为：`(.+?)`', system_msg)
        fixed_et = et_match.group(1) if et_match else 'NOT FOUND'

        key = f'{task_name} | error_type={fixed_et}'
        if key not in system_prompts:
            system_prompts[key] = {
                'task': task_name,
                'error_type': fixed_et,
                'count': 0,
                'first_line': i + 1,
                'full_prompt': system_msg
            }
        system_prompts[key]['count'] += 1

print('Distinct system prompts (task + error_type) in training data:')
print('=' * 80)
for key, info in sorted(system_prompts.items()):
    print(f'  Task: "{info["task"]}"')
    print(f'  error_type fixed: "{info["error_type"]}"')
    print(f'  count: {info["count"]}, first at line {info["first_line"]}')
    print()

# Now check: do the error_type values in the prompt files match what's in the training data?
print('\n' + '=' * 80)
print('Prompt files error_type values vs training data:')
print('=' * 80)

# Read all prompt files
import os
prompt_dir = r'C:\hyt-agent\提示词-微调版'
prompt_error_types = {}
for fname in sorted(os.listdir(prompt_dir)):
    if not fname.endswith('.txt'):
        continue
    fpath = os.path.join(prompt_dir, fname)
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()
    et_match = re.search(r'error_type.*固定为：`(.+?)`', content)
    if et_match:
        prompt_error_types[fname] = et_match.group(1)
    # Skip files without error_type (like 共享核心.txt, JSON约束.txt)

print(f'\nPrompt files with error_type definitions ({len(prompt_error_types)} files):')
for fname, et in sorted(prompt_error_types.items()):
    in_training = et in [info['error_type'] for info in system_prompts.values()]
    print(f'  {fname:40s} -> error_type="{et}"  {"[IN TRAINING]" if in_training else "[NOT IN TRAINING]"}')

print(f'\nTraining data error_type values: {sorted(set(info["error_type"] for info in system_prompts.values()))}')
print(f'Prompt files error_type values:   {sorted(set(prompt_error_types.values()))}')

# Check for conflicts: prompt files that should produce same error_type but don't
print('\n' + '=' * 80)
print('Conflict check: prompt files with same base name but different error_type:')
print('=' * 80)
from collections import defaultdict
et_to_files = defaultdict(list)
for fname, et in prompt_error_types.items():
    et_to_files[et].append(fname)

for et, files in sorted(et_to_files.items()):
    if len(files) > 1:
        print(f'  error_type="{et}" used by: {", ".join(files)}')
    else:
        print(f'  error_type="{et}" used by: {files[0]}')
