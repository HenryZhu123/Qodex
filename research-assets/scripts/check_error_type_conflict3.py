import json
import re
import os

# Compare system prompts in training data with current prompt files
# to check if the error_type definitions match exactly

prompt_dir = r'C:\hyt-agent\提示词-微调版'

# Read shared core
with open(os.path.join(prompt_dir, '共享核心.txt'), 'r', encoding='utf-8') as f:
    shared_core = f.read()

# Read task-specific prompts
task_prompts = {}
for fname in os.listdir(prompt_dir):
    if fname.endswith('.txt') and fname not in ['共享核心.txt', 'JSON约束.txt', 'README.md']:
        fpath = os.path.join(prompt_dir, fname)
        with open(fpath, 'r', encoding='utf-8') as f:
            content = f.read()
        # Extract task name
        task_match = re.search(r'# 任务：(.+?)$', content, re.MULTILINE)
        task_name = task_match.group(1).strip() if task_match else fname
        # Extract error_type
        et_match = re.search(r'error_type.*固定为：`(.+?)`', content)
        et = et_match.group(1) if et_match else None
        task_prompts[fname] = {
            'content': content,
            'task': task_name,
            'error_type': et
        }

# Get one sample per task type from training data
training_samples = {}
with open(r'C:\hyt-agent\训练集-微调版提示词\train_v1.1\train_v1.1.jsonl', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        d = json.loads(line)
        messages = d['messages']
        system_msg = ''
        for m in messages:
            if m['role'] == 'system':
                system_msg = m['content']
                break

        # Extract task name
        task_match = re.search(r'# 任务：(.+?)$', system_msg, re.MULTILINE)
        task_name = task_match.group(1).strip() if task_match else 'UNKNOWN'

        # Extract error_type
        et_match = re.search(r'error_type.*固定为：`(.+?)`', system_msg)
        et = et_match.group(1) if et_match else 'NOT FOUND'

        key = f'{task_name}'
        if key not in training_samples:
            training_samples[key] = {
                'system_prompt': system_msg,
                'error_type': et,
                'line': i + 1
            }

# Compare
print('Comparing training data system prompts with current prompt files:')
print('=' * 80)

for task_name, info in sorted(training_samples.items()):
    print(f'\n--- Task: {task_name} (line {info["line"]}) ---')
    print(f'  Training data error_type: "{info["error_type"]}"')

    # Find matching prompt file
    matching_files = []
    for fname, pinfo in task_prompts.items():
        if pinfo['task'] == task_name:
            matching_files.append((fname, pinfo))

    if not matching_files:
        print(f'  WARNING: No matching prompt file found for task "{task_name}"')
        continue

    for fname, pinfo in matching_files:
        match = 'MATCH' if pinfo['error_type'] == info['error_type'] else 'MISMATCH'
        print(f'  Prompt file: {fname}')
        print(f'    Prompt error_type: "{pinfo["error_type"]}"  -> {match}')

        # Also check if the error_type line appears in the training system prompt
        # The system prompt is shared_core + task_prompt, so let's check
        et_line = f'`error_type` 固定为：`{pinfo["error_type"]}`'
        in_training = et_line in info['system_prompt']
        print(f'    Error type line in training system prompt: {"YES" if in_training else "NO"}')

        # Check if the full prompt content is in the training system prompt
        # The training system prompt should be: shared_core + "\n" + task_prompt
        # But there might be formatting differences, so let's check key sections
        prompt_in_training = pinfo['content'] in info['system_prompt']
        print(f'    Full prompt content in training system prompt: {"YES" if prompt_in_training else "NO (may have formatting diffs)"}')

# Also check: are there any prompt files whose task name matches but error_type doesn't?
print('\n' + '=' * 80)
print('Summary of all prompt files vs training data:')
print('=' * 80)

training_ets = set(info['error_type'] for info in training_samples.values())
print(f'\nTraining data error_types: {sorted(training_ets)}')

all_prompt_ets = set(pinfo['error_type'] for pinfo in task_prompts.values() if pinfo['error_type'])
print(f'All prompt file error_types: {sorted(all_prompt_ets)}')

# Check for naming inconsistencies
print('\n--- Naming consistency check ---')
# Check: do prompt file names match their task names and error_types?
naming_issues = []
for fname, pinfo in sorted(task_prompts.items()):
    if pinfo['error_type'] is None:
        continue

    # Check if file name suggests a different language prefix than error_type
    # e.g., "日语_拼写错误.txt" should have "日文：拼写错误" not "日语：拼写错误"
    if fname.startswith('日语_'):
        if not pinfo['error_type'].startswith('日文：'):
            naming_issues.append(f'{fname}: error_type="{pinfo["error_type"]}" (expected 日文： prefix)')
    elif fname.startswith('德语_'):
        if not pinfo['error_type'].startswith('德语：'):
            naming_issues.append(f'{fname}: error_type="{pinfo["error_type"]}" (expected 德语： prefix)')
    elif fname.startswith('法语_'):
        if not pinfo['error_type'].startswith('法语：'):
            naming_issues.append(f'{fname}: error_type="{pinfo["error_type"]}" (expected 法语： prefix)')
    elif fname.startswith('英语_'):
        if not pinfo['error_type'].startswith('英语：'):
            naming_issues.append(f'{fname}: error_type="{pinfo["error_type"]}" (expected 英语： prefix)')

if naming_issues:
    print('  Issues found:')
    for issue in naming_issues:
        print(f'    {issue}')
else:
    print('  No naming inconsistencies found.')
