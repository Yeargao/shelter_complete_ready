"""Local-first care intent routing. The model may classify, never select a task or write.
All actual reports still use the existing authenticated draft/report pipeline.
"""
import re
import care_workflow as care

# Patterns describe semantic families, not the held-out dialogue fixtures.
PATTERNS={
 'healthy':r'(?:身體|健康|精神|狀況)?(?:一切|都|很|完全)?(?:正常|健康|沒問題|無異常|沒異常|沒事)(?:了)?',
 'sick':r'(?:觀察到|發現|確認|檢查出)?(?:有病|生病|不舒服|身體不適|患病)(?:了)?',
 'injured':r'(?:觀察到|發現|確認|檢查出)?(?:受傷|有傷|有傷口|受了傷)(?:了)?',
 'recovered':r'(?:(?:傷口|傷勢|受傷|傷|疾病|病|術後|手術後|身體|健康|狀況|治療|照護)(?:的)?(?:已經|已|都|完全)?(?:解決|處理好|好了|好|痊癒|康復|恢復正常|復原|癒合)|(?:已經|已|完全)?(?:康復|痊癒|復原|恢復正常))(?:了)?',
 'not_recovered':r'(?:傷口|傷勢|受傷|傷|疾病|病|術後|手術後|身體|健康|狀況|治療)?(?:還|仍|尚|暫時)?(?:沒好|沒有好|未好|未康復|沒康復|沒有康復|未痊癒|沒痊癒|沒恢復|未恢復|需要繼續治療|需要休養|還要休養)(?:了)?',
 'improving':r'(?:傷口|傷勢|受傷|傷|病|狀況|健康)?(?:有|稍微|略有)?(?:好轉|改善|好一點|好一些|變好|比較好)(?:了)?(?:[,， ]*(?:但|可是|不過)?(?:還|仍|尚)?(?:沒好|未康復|沒康復|沒有康復|未痊癒|沒痊癒|未完全恢復|未完全好))?',
 'worsening':r'(?:傷口|傷勢|受傷|傷|病|狀況|健康)?(?:仍|還|一直|完全)?(?:沒有改善|沒改善|未改善|變差|惡化|變嚴重|更嚴重|沒有起色)(?:了)?',
 'abnormal':r'(?:術後|手術後|傷口|狀況)?(?:發現|出現|有)?(?:異常|不正常|不對勁|感染跡象)(?:了)?',
 'yes':r'(?:(?:疫苗|針|驅蟲)(?:之前|以前|已經|已|曾經|曾)?(?:打過|打了|打完|接種過|施打過|施打|接種|做過|完成|做完)|(?:之前|以前|已經|已|曾經|曾)?(?:打過|接種過|施打過|驅蟲過|驅過蟲|做過驅蟲|已驅蟲|已施打|已接種))(?:了)?',
 'no':r'(?:(?:疫苗|驅蟲)(?:之前|以前|尚|還|從來)?(?:沒|沒有|未)(?:打過|接種過|施打過|打|接種|施打|做過|做|完成|驅蟲)?|(?:還|尚|從來)?(?:沒|沒有|未)(?:打過疫苗|接種過疫苗|打疫苗|接種疫苗|施打疫苗|驅過蟲|驅蟲|做過驅蟲|施打|接種))(?:過)?',
 'done':r'(?:(?:疫苗|針|驅蟲|絕育|手術|絕育手術)(?:順利|已經|已|剛剛)?(?:打完|打好|做完|做成|成功|完成|施打完成|接種完成)|(?:已經|已|剛剛|順利)?(?:成功|完成|做完|打完|打好了|處理完成)|(?:疫苗|驅蟲|絕育)?(?:紀錄|資料|狀態|登錄|檔案)(?:已經|已|都)?(?:更新|補齊|登記好|登記完|填好|寫好|改好|核對完)|(?:已經|已)?(?:更新|登記完|登記好|補齊|填好|寫好))(?:了)?',
 'failed':r'(?:疫苗|針|驅蟲)?(?:這次|本次|剛剛)?(?:失敗|沒成功|未成功|沒有成功|沒打成|沒做成|未能完成|沒完成)(?:了)?',
 'already':r'(?:(?:之前|以前|早就|已經|已|曾經|曾)?(?:絕育過|做過絕育|已絕育|結紮過|做過結紮|已結紮)|(?:絕育|結紮)(?:之前|以前|早就|已經|已)?(?:做過|完成過))(?:了)?',
 'suitable':r'(?:評估後|獸醫評估|獸醫確認|確認)?(?:現在|目前|已經)?(?:適合|可以|能夠|能|可)(?:接受|進行|安排|做)?(?:絕育|結紮|手術)(?:了)?',
 'defer':r'(?:評估後|獸醫評估|獸醫確認|確認)?(?:目前|現在|暫時|暫且|暫)?(?:不適合|不能|不宜|無法|不可以)(?:接受|進行|安排|做)?(?:絕育|結紮|手術)(?:了)?',
 'incomplete':r'(?:絕育手術|絕育|手術)?(?:這次|本次)?(?:未完成|沒完成|沒有完成|中止|取消|失敗|沒做完|沒有做完)(?:了)?',
}
NEXT=re.compile(r'(?:下一步(?:是什麼|要做什麼|呢|怎麼做)?|接下來(?:要做什麼|怎麼做|呢)?|後續(?:要做什麼|是什麼|呢)?|之後(?:會怎樣|會發生什麼|會做什麼|要做什麼)|然後呢)[?？。！!\s]*$')
READ=re.compile(r'查詢|查看|查一下|列出|統計|有沒有|是否|哪些|幾項|多少|紀錄[?？]|日期[?？]|怎麼回報|如何回報|如何操作|怎麼操作|按哪|按什麼|要填|收回|撤回|更正|修改|設定|結案|標記已解決|刪除|入所|離所|指派|派工|用藥|劑量|診斷|什麼藥|怎麼治療|如何治療')
UNCERTAIN=re.compile(r'不要|不確定|不清楚|可能|好像|似乎|猜|假設|如果|假如|不是|尚不知道')
GROUP_HINTS={
 '健康照護':r'健康|身體|不適|不舒服|受傷|傷口|傷勢|傷|病|治療|康復|痊癒|好轉|惡化|改善|復原|恢復|沒好|異常',
 '疫苗':r'疫苗|接種|施打|打針|針|打過|打完|沒打',
 '驅蟲':r'驅蟲|驅過蟲',
 '絕育':r'絕育|結紮|手術|術後',
}
def matching_labels(text):
    explicit=[label for label in care.RULES if care.display_label(label) in text or label in text]
    if explicit:return explicit
    groups=[g for g,p in GROUP_HINTS.items() if re.search(p,text)]
    if '絕育' in groups and re.search(r'術後|手術後',text):return ['術後健康追蹤']
    if len(groups)>1:return []
    return list(care.GROUPS[groups[0]]) if groups else list(care.RULES)

def choices(text,labels):
    """Return all plausible (task label, outcome) pairs; never choose by list order."""
    text=text.strip(' ，,。！!：:')
    for label in sorted(care.RULES,key=lambda x:len(care.display_label(x)),reverse=True):
        text=text.replace(care.display_label(label),'').replace(label,'')
    text=re.sub(r'^(?:請幫我|幫我|我要|我想|回報|結果[:：]?|牠|它|這隻|該動物|那隻|我|確認|檢查後|觀察後)[ ，,:：]*','',text)
    text=text.strip(' ，,。！!：:')
    pairs=[]
    for label in labels:
        code=care.result_code(label,text)
        valid={r[0] for r in care.RULES[label]}
        if code in valid:
            pairs.append((label,code));continue
        for c,_,_ in care.RULES[label]:
            if re.fullmatch(PATTERNS.get(c,r'(?!)'),text):
                pairs.append((label,c))
    return list(dict.fromkeys(pairs))

# Few-shot examples are semantic descriptions; acceptance dialogues live separately.
PROMPT="""只辨識收容所照護結果。輸入已去除動物識別資訊；候選是唯一允許的任務與結果。
不要推測、診斷、選擇動物或執行操作。若未明確陳述結果、含否定歧義、詢問實際紀錄、或可對應多個候選，回傳空 selections。
例如：傷處已經癒合 → recovered；接種沒有成功 → failed；獸醫認為目前不宜結紮 → defer；單純說要打疫苗 → 空 selections。
只回傳候選 selections 的整數索引；最多一個。"""
def model_choice(connect,text,pairs):
    from llm_service import generate_tool
    if not pairs:return []
    schema={'type':'object','properties':{'selections':{'type':'array','items':{'type':'integer'},'maxItems':1}},'required':['selections'],'additionalProperties':False}
    def validate(value):
        if not isinstance(value,dict) or set(value)!={'selections'}:raise ValueError('bad intent')
        ids=value['selections']
        if not isinstance(ids,list) or len(ids)>1 or any(type(i) is not int or not 0<=i<len(pairs) for i in ids):raise ValueError('bad selection')
        return [pairs[i] for i in ids]
    data={'text':text,'candidates':[{'task':care.display_label(label),'result':care.result_title(label,code),'code':code} for label,code in pairs]}
    result,_=generate_tool(connect,PROMPT,data,schema,validate,function_name='classify_care_outcome')
    return result or []

def next_text(label,code,from_surgery=None):
    title=care.result_title(label,code)
    if label=='更新疫苗紀錄' and code=='done':
        return f'回報「{title}」後，依可信施打日期加12個月建立下次疫苗施打任務，不用手動填下次日期。'
    if label=='更新絕育狀態' and code=='done':
        detail=('產生術後健康追蹤' if from_surgery else '結束本次絕育流程') if from_surgery is not None else '若來源是手術成功，產生術後健康追蹤；若來源是既有絕育紀錄，任務結束'
        return f'回報「{title}」後，更新為已絕育；{detail}。'
    child=care.next_task(label,code)
    if not child:
        return f'回報「{title}」後，'+('健康狀態更新為健康，' if code in ('healthy','recovered') else '更新為已驅蟲，' if label in ('更新驅蟲狀態','更新驅蟲紀錄') else '')+'結束本次流程，不產生後續任務。'
    retry='，最早於隔日執行' if child==label and code in ('failed','defer','improving','not_recovered') else ''
    issue='建立問題回報，' if code in care.ISSUE_RESULTS else ''
    return f'回報「{title}」後，{issue}產生「{care.display_label(child)}」任務{retry}，須由管理者指派。'
