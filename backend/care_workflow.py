"""Care-task state machine. Keep historical treatment IDs, display 傷病治療."""
RULES = {
  "健康狀態待確認": [
    [
      "healthy",
      "健康",
      None
    ],
    [
      "sick",
      "生病",
      "優先確認健康狀況"
    ],
    [
      "injured",
      "受傷",
      "優先確認健康狀況"
    ]
  ],
  "優先確認健康狀況": [
    [
      "recovered",
      "已康復",
      None
    ],
    [
      "not_recovered",
      "尚未康復",
      "健康問題追蹤"
    ]
  ],
  "健康問題追蹤": [
    [
      "recovered",
      "已康復",
      None
    ],
    [
      "improving",
      "狀況改善但未康復",
      "健康問題追蹤"
    ],
    [
      "worsening",
      "狀況未改善／惡化",
      "優先確認健康狀況"
    ]
  ],
  "確認疫苗紀錄": [
    [
      "yes",
      "已施打",
      "更新疫苗紀錄"
    ],
    [
      "no",
      "未施打",
      "疫苗施打"
    ]
  ],
  "疫苗施打": [
    [
      "done",
      "成功",
      "更新疫苗紀錄"
    ],
    [
      "failed",
      "失敗",
      "疫苗施打"
    ]
  ],
  "更新疫苗紀錄": [
    [
      "done",
      "已更新",
      None
    ]
  ],
  "確認驅蟲紀錄": [
    [
      "yes",
      "已驅蟲",
      "更新驅蟲狀態"
    ],
    [
      "no",
      "未驅蟲",
      "基礎驅蟲"
    ]
  ],
  "基礎驅蟲": [
    [
      "done",
      "成功",
      "更新驅蟲紀錄"
    ],
    [
      "failed",
      "失敗",
      "基礎驅蟲"
    ]
  ],
  "更新驅蟲狀態": [
    [
      "done",
      "已更新",
      None
    ]
  ],
  "更新驅蟲紀錄": [
    [
      "done",
      "已更新",
      None
    ]
  ],
  "評估絕育安排": [
    [
      "already",
      "已絕育",
      "更新絕育狀態"
    ],
    [
      "suitable",
      "適合絕育",
      "絕育手術"
    ],
    [
      "defer",
      "暫不適合絕育",
      "評估絕育安排"
    ]
  ],
  "絕育手術": [
    [
      "done",
      "成功",
      "更新絕育狀態"
    ],
    [
      "incomplete",
      "未完成",
      "評估絕育安排"
    ]
  ],
  "更新絕育狀態": [
    [
      "done",
      "已更新",
      None
    ]
  ],
  "術後健康追蹤": [
    [
      "recovered",
      "已康復",
      None
    ],
    [
      "not_recovered",
      "尚未康復",
      "術後健康追蹤"
    ],
    [
      "abnormal",
      "出現異常",
      "優先確認健康狀況"
    ]
  ]
}
GROUPS = {
  "健康照護": [
    "健康狀態待確認",
    "優先確認健康狀況",
    "健康問題追蹤",
    "術後健康追蹤"
  ],
  "疫苗": [
    "確認疫苗紀錄",
    "疫苗施打",
    "更新疫苗紀錄"
  ],
  "驅蟲": [
    "確認驅蟲紀錄",
    "基礎驅蟲",
    "更新驅蟲狀態",
    "更新驅蟲紀錄"
  ],
  "絕育": [
    "評估絕育安排",
    "絕育手術",
    "更新絕育狀態",
    "術後健康追蹤"
  ]
}
ADDITIONAL_TASKS = {
    '更新疫苗紀錄': ('admin','admin:records',0.25,False),
    '更新驅蟲狀態': ('admin','admin:records',0.25,False),
    '更新驅蟲紀錄': ('admin','admin:records',0.25,False),
    '絕育手術': ('health','health:veterinary',1.0,False),
    '更新絕育狀態': ('admin','admin:records',0.25,False),
    '術後健康追蹤': ('health','health:veterinary',0.5,False),
}
NOTE_RESULTS = {'sick','injured','failed','not_recovered','improving','worsening','defer','incomplete','abnormal','reported'}
ISSUE_RESULTS = {'sick','injured','failed','worsening','abnormal','reported'}
def display_label(label):
    return '傷病治療' if label=='優先確認健康狀況' else label

def allowed(label):
    extra={'優先確認健康狀況':('healthy','sick','injured','reported'),
           '健康問題追蹤':('reported',),'評估絕育安排':('done',)}
    return tuple(row[0] for row in RULES.get(label,(('done','完成',None),)))+extra.get(label,())

def outcomes(label):
    return '／'.join(row[1] for row in RULES.get(label,(('done','完成',None),)))

def next_task(label,result,from_surgery=False):
    if label=='更新絕育狀態' and result=='done' and from_surgery:
        return '術後健康追蹤'
    if label=='優先確認健康狀況' and result in ('sick','injured','reported'):
        return '健康問題追蹤'
    if label=='健康問題追蹤' and result=='reported':
        return '健康問題追蹤'
    if label=='評估絕育安排' and result=='done':
        return '評估絕育安排'
    return next((row[2] for row in RULES.get(label,()) if row[0]==result),None)

def result_code(label,text):
    text=text.strip().strip('。！! ').replace('/','／')
    for code,title,_ in RULES.get(label,(('done','完成',None),)):
        if text in (title,code):
            return code
    aliases={'未接種':'no','已接種':'yes','已完成':'done','完成':'done','成功':'done',
             '已更新':'done','未康復':'not_recovered','改善但未康復':'improving',
             '狀況未改善':'worsening','惡化':'worsening','未改善':'worsening','異常':'abnormal',
             '暫不適合':'defer','已回報':'reported','已追蹤':'reported'}
    code=aliases.get(text)
    return code if code in allowed(label) else None

def describe_next(label,result):
    if label=='更新疫苗紀錄' and result=='done':
        return '到達下次施打日期 → 疫苗施打'
    if label=='更新絕育狀態' and result=='done':
        return '手術成功來源 → 術後健康追蹤；已絕育核對來源 → 任務結束'
    target=next_task(label,result)
    return display_label(target) if target else '任務結束'

def workflow_lines(group):
    lines=[]
    for label in GROUPS[group]:
        # Postoperative follow-up belongs to the sterilization journey in user-facing guides.
        if group=='健康照護' and label=='術後健康追蹤':
            continue
        for result,title,_ in RULES[label]:
            if label=='更新疫苗紀錄':
                lines.append('更新疫苗紀錄 →（到達下次施打日期）→ 疫苗施打')
            elif label=='更新絕育狀態':
                lines.extend(['更新絕育狀態（已絕育核對來源） → 任務結束',
                              '更新絕育狀態（手術成功來源） → 術後健康追蹤'])
            else:
                lines.append(f'{display_label(label)} →（{title}）→ {describe_next(label,result)}')
    if group=='驅蟲':
        lines.append('動物重新入所 → 基礎驅蟲')
    return lines

def result_title(label,result,fallback=None):
    return next((row[1] for row in RULES.get(label,()) if row[0]==result), fallback if fallback is not None else result)
