import json
import sys

with open('divar_sample_post.json', encoding='utf-8') as f:
    d = json.load(f)

lines = []
lines.append('Contact: ' + json.dumps(d.get('contact'), ensure_ascii=False))
lines.append('SEO: ' + json.dumps(d.get('seo'), ensure_ascii=False))

for i, sec in enumerate(d.get('sections', [])):
    sname = sec.get('section_name')
    lines.append(f'=== Section {i} {sname} ===')
    for w in sec.get('widgets', []):
        wt = w.get('widget_type')
        wdata = w.get('data', {})
        lines.append(f'  Widget: {wt}')
        if wt in ['UNEXPANDABLE_ROW', 'GROUP_INFO_ROW', 'TITLE_ROW', 'LEGEND_TITLE_ROW', 'DESCRIPTION_ROW', 'PROPERTY_LIST', 'GROUP_FEATURE_ROW', 'SCORE_ROW', 'FEATURE_ROW', 'CHIPS_ROW', 'MAP_ROW']:
            lines.append('    data: ' + json.dumps(wdata, ensure_ascii=False))
        elif wt in ['IMAGE_CAROUSEL', 'IMAGE_SLIDER', 'IMAGES_ROW']:
            items = wdata.get('items', [])
            lines.append(f'    items count: {len(items)}')
            for it in items:
                lines.append('      img item: ' + json.dumps(it, ensure_ascii=False))

with open('divar_parsed_sample.txt', 'w', encoding='utf-8') as out:
    out.write('\n'.join(lines))
print('Written to divar_parsed_sample.txt')
