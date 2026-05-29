import json, glob, os
for f in sorted(glob.glob('models/v3/arch_h09*_history.json')):
    name = os.path.basename(f).replace('arch_', '').replace('_history.json', '')
    try:
        d = json.load(open(f))
    except Exception as e:
        print(f'{name}: (unreadable: {e})')
        continue
    if not d:
        print(f'{name}: (empty)')
        continue
    floors = [p['mean_floor'] for p in d]
    acts = [p['mean_act'] for p in d]
    wins = [p['win_rate'] for p in d]
    n = len(d)
    last6 = d[-6:]
    print(f'{name}: evals={n} steps={d[-1]["timesteps"]:,}')
    print(f'   mean_floor: max={max(floors):.2f}  recent6={sum(p["mean_floor"] for p in last6)/len(last6):.2f}  allavg={sum(floors)/n:.2f}')
    print(f'   mean_act:   max={max(acts):.2f}  recent6={sum(p["mean_act"] for p in last6)/len(last6):.2f}')
    print(f'   win_rate:   max={max(wins):.0%}  recent6={sum(p["win_rate"] for p in last6)/len(last6):.0%}')
