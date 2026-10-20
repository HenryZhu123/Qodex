import json
import re

# Extract task type from system messages
task_types = {}

with open(r'C:\hyt-agent\训练集-微调版提示词\train_v1.1\train_v1.1.jsonl', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        d = json.loads(line)
        messages = d['messages']
        system_msg = ''
        for m in messages:
            if m['role'] == 'system':
                system_msg = m['content']
                break

        # Find error_type fixed value in system prompt
        match = re.search(r'error_type.*固定为：`(.+?)`', system_msg)
        if match:
            et_fixed = match.group(1)
        else:
            et_fixed = 'NOT FOUND'

        if et_fixed not in task_types:
            task_types[et_fixed] = []
        task_types[et_fixed].append(i+1)

print('Task types (error_type fixed in system prompt) found in training data:')
for et in sorted(task_types.keys()):
    count = len(task_types[et])
    print(f'  "{et}"  (count={count})')
print(f'Total distinct: {len(task_types)}')

# Now cross-reference: for each sample, check if the error_type in assistant output matches the fixed error_type in system prompt
print('\n' + '='*80)
print('Cross-reference: system prompt fixed error_type vs assistant output error_type')
print('='*80)

mismatches = []
match_count = 0

with open(r'C:\hyt-agent\训练集-微调版提示词\train_v1.1\train_v1.1.jsonl', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        d = json.loads(line)
        messages = d['messages']
        system_msg = ''
        assistant_msg = ''
        for m in messages:
            if m['role'] == 'system':
                system_msg = m['content']
            elif m['role'] == 'assistant':
                assistant_msg = m['content']

        # Extract fixed error_type from system prompt
        match = re.search(r'error_type.*固定为：`(.+?)`', system_msg)
        if match:
            fixed_et = match.group(1)
        else:
            fixed_et = 'NOT FOUND'

        # Parse assistant output
        try:
            result = json.loads(assistant_msg)
        except:
            continue

        if not result.get('has_error', False) or not result.get('errors'):
            continue

        # Check each error in the output
        for err in result['errors']:
            actual_et = err.get('error_type', 'MISSING')
            if actual_et == fixed_et:
                match_count += 1
            else:
                mismatches.append({
                    'line': i + 1,
                    'fixed_in_prompt': fixed_et,
                    'actual_in_output': actual_et,
                    'reason': result.get('reason', '')[:80]
                })

print(f'Matches: {match_count}')
print(f'Mismatches: {len(mismatches)}')

if mismatches:
    print('\n--- Mismatch details ---')
    for m in mismatches[:30]:
        print(f'  Line {m["line"]}: prompt says "{m["fixed_in_prompt"]}" but output says "{m["actual_in_output"]}"')
        print(f'    reason: {m["reason"]}')
