"""Role-aware, local-first product guidance and operational questions.

No medical diagnosis, autonomous writes or LLM calls. Suggestions are ordinary chat
requests, and existing authorization and confirmation endpoints remain authoritative.
"""
import re
from datetime import timedelta
import chat_intent as ci
from fastapi import HTTPException

HEALTH={'healthy':'健康','sick':'生病','injured':'受傷','serious':'嚴重狀況','unknown':'未確認','needs_review':'待確認'}
STATE={'pending':'待完成','in_progress':'執行中','done':'已完成','cancelled':'已取消'}
HEALTH_TASKS=('健康狀態待確認','優先確認健康狀況','健康問題追蹤')
HOW=re.compile(r'怎麼(?:做|辦|處理|操作|使用|回報|修改|新增|安排|查看|查詢|取消|登記|核對|重排|指派|撤回|收回|開始|設定|更正|排班|分配|最佳化)|如何|要怎麼|應該|下一步|該怎麼|要做什麼|去哪|在哪(?:裡|里)?|哪個頁面|哪裡|哪裏|哪边|哪邊')
PRONOUN=re.compile(r'牠|它|這隻|該動物|那隻|這個動物|幫他|幫她|他(?:的|還|有|需要|要|生病|受傷)')
GROUP=re.compile(r'哪些|多少|幾隻|所有|全部|名單|清單|列出')
def link(path,label):return {'path':path,'label':label}
def prompt(label,question):return {'label':label,'question':question}

def guide(db,uid,q,active,current,resolve,resource_totals,topic=None):
    """Return (turn, active animal) or None. All staff reads are explicitly scoped."""
    manager=uid==1
    staff=None
    if not manager:
        row=db.execute('SELECT s.id FROM weekly_staff_accounts a JOIN staff s ON s.id=a.staff_id WHERE a.user_id=? AND s.profile_id=1',(uid,)).fetchone()
        if not row:raise HTTPException(403,'目前帳號未連結員工')
        staff=row[0]
    def reply(text,links=(),suggestions=(),sources=(),target=active,topic=None):
        return ({'answer':{'answer':text,'source':'db' if sources else 'rules','sources':list(sources),'context':None,'fallback_reason':None,'queried_at':None},
                 'links':list(links),'suggestions':list(suggestions),'workflow_topic':topic},target)
    def role_denied():
        return reply('此操作需要管理者權限。你可以在個人工作台查閱、回報自己的任務；如需修改動物行政資料或班表，請聯絡管理者。',[link('/','個人工作台')])
    def select_target():
        found=resolve(db,q)
        if found is None and PRONOUN.search(q) and not re.search(r'[A-Za-z]{2,}',q):found=active
        if found is None:return None
        a=db.execute('SELECT id,name,health_status,is_active,intake_date,vaccinated,dewormed FROM animals WHERE id=?',(found,)).fetchone()
        if not a:raise HTTPException(404,'找不到指定動物')
        if not manager and not db.execute("SELECT 1 FROM weekly_tasks WHERE animal_id=? AND staff_id=? AND state!='cancelled'",(found,staff)).fetchone():
            raise HTTPException(403,'目前沒有可查看的動物紀錄；若現場發現異常，請立即通知主管或獸醫，不必等待系統派工。')
        return a
    def own_tasks(aid,all_days=False):
        sql="""SELECT t.task_id,t.label,t.day,t.start,t.state,t.priority,t.due,t.staff_id,s.name AS staff_name
            FROM weekly_tasks t LEFT JOIN staff s ON s.id=t.staff_id WHERE t.animal_id=? AND t.state!='cancelled'"""
        args=[aid]
        if not manager:sql+=' AND t.staff_id=?';args.append(staff)
        if not all_days:sql+=" AND t.state IN ('pending','in_progress')"
        return [dict(r) for r in db.execute(sql+' ORDER BY t.priority,COALESCE(t.day,t.due),t.start,t.task_id',args)]
    def task_line(t):
        when=(t['day']+(f" {t['start']//4:02d}:{t['start']%4*15:02d}" if t['start'] is not None else '')) if t['day'] else ('待指派，期限 '+str(t['due'] or '未設定'))
        return f"{t['label']} · {STATE.get(t['state'],t['state'])} · {when}"+(f" · {t['staff_name'] or '未指派'}" if manager else '')
    def health_flow():
        a=select_target()
        links=[link('/resources','資源配置') ,link('/health','健康行政核對')] if manager else [link('/','個人工作台')]
        prompts=[]
        lines=[]
        sources=[]
        if a:
            aid=a['id'];name=a['name'];target=f"{name} #{aid}"
            lines.append(f"{target}｜目前健康登錄：{HEALTH.get(a['health_status'],'未確認')}。")
            sources.append('動物 #'+str(aid))
            links.insert(0,link('/animals/'+str(aid),'動物詳細資料'))
            if not a['is_active']:
                return reply('\n'.join(lines+['此動物已離所，不應安排在所照護；如有歷史紀錄問題請聯絡管理者核對。']),links,sources=sources,target=aid)
            tasks=[t for t in own_tasks(aid) if t['label'] in HEALTH_TASKS]
            if tasks:
                lines.append('目前可查看的未完成健康任務：')
                for t in tasks[:8]:
                    lines.append(task_line(t));sources.append('任務 '+t['task_id'])
            else:lines.append('目前沒有可查看的未完成健康任務。')
        else:
            aid=None;tasks=[]
            if PRONOUN.search(q):
                lines.append('目前尚未指定動物。可提供動物名稱或 #編號，我就能核對相關任務。')
        lines.append('若現場發現動物生病、受傷或明顯異常，先通知主管及獸醫；有急迫危險時立即依收容所緊急流程處理，不必等系統派工。不要自行診斷或給藥。')
        if manager:
            lines.extend(['1. 在動物詳細資料核對健康登錄及最近照護回報；只有確認實際狀況後才修改登錄。',
                          '2. 到資源配置檢查「優先確認健康狀況」或「健康問題追蹤」任務。若尚未建立，可建立任務草案；若已有，避免重複建立。',
                          '3. 指派具備相應資格的員工，預覽排程並確認套用；緊急處置不能只依賴排程。',
                          '4. 查看員工回報及待處理異常，依實際處理結果在資源配置核對是否結案。'])
            if aid:
                prompts.append(prompt('查最近照護回報',f'動物 #{aid} 最近照護回報'))
                if a['health_status'] not in ('sick','injured','serious'):
                    prompts.append(prompt('生病已確認，建立健康修改草案',f'動物 #{aid} 健康：生病'))
                    prompts.append(prompt('受傷已確認，建立健康修改草案',f'動物 #{aid} 健康：受傷'))
                if not any(t['label']=='優先確認健康狀況' for t in tasks):
                    prompts.append(prompt('建立今日優先健康確認任務',f'建立動物 #{aid} 今天的優先確認健康狀況任務'))
                if not any(t['label']=='健康問題追蹤' for t in tasks):
                    prompts.append(prompt('建立今日健康問題追蹤任務',f'建立動物 #{aid} 今天的健康問題追蹤任務'))
        else:
            lines.extend(['1. 在個人工作台開啟自己被指派的照護任務，選擇實際觀察到的結果，填寫症狀、發現時間與必要照片。',
                          '2. 若回報生病或受傷，系統會記錄異常並依規則產生後續任務；後續任務由管理者確認派工。',
                          '3. 若沒有自己的可回報任務，立即通知主管安排，不要代替他人回報或假設已完成。',
                          '4. 需要照片或更正既有回報時，使用個人工作台。'])
            if aid:
                for t in tasks:
                    if t['day']==current.isoformat() and t['label'] in HEALTH_TASKS[:2]:
                        for label in ('生病','受傷'):
                            prompts.append(prompt(f'回報{label}（需填備註）',f"回報 {t['task_id']} 結果：{label}"))
                    elif t['day']==current.isoformat() and t['label']=='健康問題追蹤':
                        prompts.append(prompt('回報健康追蹤（需填備註）',f"回報 {t['task_id']} 結果：已追蹤"))
                prompts.append(prompt('查最近照護回報',f'動物 #{aid} 最近照護回報'))
        return reply('\n'.join(lines),links,prompts,sources,aid if a else None,topic='health')
    # Medical instructions are not a software operation. Never output drug/dose guidance.
    if re.search(r'劑量|用藥|給藥|開藥|吃什麼藥|用什麼藥|怎麼治療|如何治療|診斷',q):
        return reply('收容所助理只能協助登錄、回報及查詢照護資料，不能提供診斷、藥物或劑量建議。請通知獸醫；若情況緊急，立即依現場緊急流程處置。',[link('/resources' if manager else '/','資源配置' if manager else '個人工作台')])
    how=bool(HOW.search(q))
    if topic=='health' and re.fullmatch(r'(?:那|所以|接著|然後|牠|它|這隻|該動物|的|\s)*(?:下一步|接下來)(?:呢|要怎麼做|該怎麼辦|怎麼做|要做什麼)?[?？。]*',q):
        if active and not PRONOUN.search(q):q='牠'+q
        return health_flow()
    if how and re.search(r'生病|受傷|傷病|健康異常|身體不適|身體不好|異常|嘔吐|拉肚子|沒精神|不吃|流血|呼吸困難',q) and not re.search(r'刪除|刪掉|撤銷|復原|收回|撤回|結案|更正|為什麼|為何',q):
        return health_flow()
    if not how and not GROUP.search(q) and not re.search(r'回報|修改|設定|改成|[:：=]|[?？]|是否|沒有|沒|不確定|可能|如果|假設',q) and re.search(r'(?:生病|受傷|嘔吐|拉肚子|沒精神|不吃東西|流血|呼吸困難)(?:了|了。|。)?$',q):
        return health_flow()
    if not manager and re.search(r'替|幫|代',q) and re.search(r'其他員工|同事|別人',q) and '回報' in q:
        return role_denied()
    # Explicit requests for unsupported mutations should give the correct page, not silently query.
    direct=not how and bool(re.search(r'^(?:請|幫我|請幫我|我要|我想|直接幫我|可以幫我)',q)) and not bool(re.search(r'查詢|查看|列出|哪些|多少|[?？]',q))
    if (how or direct) and re.search(r'手動指派|指派給|安排給|(?:指派|派工|分配).*(?:員工|人員)|(?:員工|人員).*(?:指派|派工)|直接.*派工|幫.*指派',q) and not re.search(r'建立.*任務|新增.*任務|請假|排班|出勤',q):
        if not manager:return role_denied()
        return reply('請到資源配置的待指派任務池，選擇指定任務；在任務詳細資料選擇員工、日期及開始時間，按「儲存指派」。系統會驗證員工技能、工時及時間衝突。聊天不會直接更動指派。',[link('/resources','資源配置')])
    if direct and re.search(r'結案|標記已解決|解除異常',q):
        if not manager:return role_denied()
        return reply('請在資源配置找出相應已回報任務，確認實際問題已解決，再按「標記已解決」。聊天尚不直接結案。',[link('/resources','資源配置')])
    if how:
        if re.search(r'飼料|庫存',q) and re.search(r'修改|更新|設定|補貨|盤點',q):
            if not manager:return role_denied()
            return reply('請在總覽核對收容所資源設定及實際盤點；目前可直接查詢系統登錄庫存與估算需求。若頁面未提供庫存編輯，請由管理者依既有設定流程更新，不會透過聊天自行扣庫存。',[link('/','總覽')],[prompt('查詢庫存','飼料庫存還剩多少？')])
        if re.search(r'取消|收回|撤回|復原|改回|更正',q) and re.search(r'回報|任務',q):
            if manager:return reply('管理者不能代替員工收回回報。請原回報員工至個人工作台，開啟該筆已回報任務；能否收回由日期、任務狀態及後續處理紀錄決定。若已不可收回，請依行政核對流程處理。',[link('/resources','資源配置')])
            return reply('在個人工作台開啟該筆已回報任務，若仍符合系統條件，按「收回回報」並確認；若已結案、非當日或已有後續變更，請聯絡管理者核對。',[link('/','個人工作台')])
        if re.search(r'結案|解除異常|異常處理完成',q):
            if not manager:return role_denied()
            return reply('請至資源配置，找出該筆已完成任務的待處理異常，確認實際問題已處理，再於任務詳細資料按「標記已解決」。結案不是自動將動物判定為健康；健康登錄仍須核對。',[link('/resources','資源配置')])
        if re.search(r'請假|缺席|不能上班|不來上班|班表|排班|出勤|最佳化|重排|派工|指派|分配',q):
            if not manager:
                return reply('員工不能自行更動派工或班表。若不能出勤，請立即告知管理者；在個人工作台查看調整後的任務，不要自行回報未執行的工作。',[link('/','個人工作台')])
            return reply('到資源配置，先選擇日曆日期，再展開「每日班表與員工設定」，選擇員工、修改出勤或班表，按「儲存班表」；檢查受影響的未完成任務，再預覽最佳化派工，核對技能、工時及時間，最後確認儲存。已完成任務保留；已鎖定任務請人工核對。',[link('/resources','資源配置')],[prompt('查詢待指派任務','這週有哪些任務尚未安排？'),prompt('查詢可用工時','今天哪些員工有剩餘工時？')])
        if re.search(r'離所|送養|重新入所|入所|新增動物|建檔',q):
            if not manager:return role_denied()
            if '重新入所' in q:return reply('到動物列表 → 新增動物 → 以舊離所編號重新入所，選擇原動物編號及新的入所日期，確認後保留原有入離所歷史；不要建立重複動物。',[link('/animals/new','重新入所')])
            if re.search(r'離所|送養',q):return reply('到動物列表，選擇該動物的「離所」，填寫離所日期及實際原因（例如送養），確認後才更新在所狀態；歷史紀錄保留，待執行任務依原有規則處理。',[link('/animals','動物列表')])
            return reply('到動物列表 → 新增動物，填寫名稱、物種、入所日期等資料；上傳照片時可先比對既有動物。疫苗、驅蟲及健康不明就選待確認，不捏造日期。若曾離所，使用重新入所而非新增。',[link('/animals/new','新增動物'),link('/animals','動物列表')])
        if re.search(r'疫苗|驅蟲',q):
            which='疫苗' if '疫苗' in q else '驅蟲'
            a=select_target()
            links=[link('/health','健康行政核對')] if manager else [link('/','個人工作台')]
            if a:links.insert(0,link('/animals/'+str(a['id']),'動物詳細資料'))
            if manager:
                return reply(f'先核對動物的{which}登錄及實際紀錄。到健康行政核對或動物詳細資料查看待辦；日期不明時只登錄已知狀態，不能自行填寫日期。已有紀錄需更正時，先核對原紀錄，再使用修改草案確認。',[*links],([prompt('查詢'+which+'紀錄',f"動物 #{a['id']} {which}紀錄？")] if a else []),target=a['id'] if a else active)
            return reply(f'到個人工作台開啟自己的「確認{which}紀錄」任務，依實際紀錄選擇結果。若是施作任務，只在確實完成後回報；需填日期或照片時使用工作台。沒有任務或不確定紀錄時，請聯絡管理者。',links,target=a['id'] if a else active)
        if re.search(r'回報|完成任務|上傳照片|照護摘要|備註',q):
            if manager:return reply('照護回報由被指派的員工操作。管理者可在資源配置查看已完成任務、回報備註與異常；不要代替員工回報。',[link('/resources','資源配置')])
            return reply('個人工作台 → 選擇自己的日期與任務 → 依任務選項回報實際結果；異常填寫備註及必要照片。確認後查看已回報狀態；未執行不得回報完成。',[link('/','個人工作台')],[prompt('查看今天待辦','我今天有哪些未完成任務？')])
        if re.search(r'任務|照護|工作',q):
            return reply('管理者：在資源配置檢查待指派任務池，建立或選擇任務、指派員工並確認排程。' if manager else '照護人員：在個人工作台選日期，開啟自己的任務、查看照護重點，執行後回報實際結果。',[link('/resources' if manager else '/','資源配置' if manager else '個人工作台')])
    if re.search(r'我有什麼權限|我的權限|我能操作什麼|^(?:你|助理|Chatbot|AI)?\s*(?:可以|能)(?:幫我)?(?:做什麼|做哪些事|幫什麼)|^使用說明$|^怎麼使用(?:這個|本)?(?:程式|系統|網站|助理)',q,re.I):
        return reply('你可以查詢動物、健康及醫療紀錄、任務與員工工時，也可建立動物資料修改或照護任務草案。確認才會執行。' if manager else '你可以查詢自己的班表、待辦及已完成任務、獲授權的動物紀錄，並回報自己的任務。不能修改其他員工的任務或管理者資料。',[link('/resources' if manager else '/','資源配置' if manager else '個人工作台')],[prompt('動物生病後怎麼做','某動物生病了之後要怎麼做？'),prompt('今天有哪些未完成任務','今天有哪些未完成任務？')])
    if not how and re.search(r'飼料|食物',q) and re.search(r'庫存|剩|多少|夠|需求',q) and not re.search(r'提醒|通知|修改|設定|更新|新增|昨天|明天|上週|下週|未來|過去|歷史|統計|報表|分布|比較',q):
        if not manager:return role_denied()
        p=db.execute('SELECT food_stock_kg,food_rate,care_minutes FROM profiles WHERE id=1').fetchone()
        if not p:return reply('目前沒有收容所資源設定。',[link('/','總覽')])
        animals=[dict(r) for r in db.execute('SELECT * FROM animals WHERE is_active=1')]
        food,_=resource_totals(animals,p['food_rate'],p['care_minutes'])
        stock=float(p['food_stock_kg'])
        lines=[f'飼料設定庫存：{stock:g} 公斤。',f'目前每日估算需求：{food:.2f} 公斤。']
        if food>0:lines.append(f'以目前需求固定且無補貨估算，可供 {stock/food:.1f} 天。')
        lines.append('庫存為系統登錄值，實際存量仍需盤點；不代表每日消耗已自動扣除。')
        return reply('\n'.join(lines),[link('/','總覽')],sources=['收容所資源設定 #1','在所動物需求設定'])
    if not how and re.search(r'疫苗.*(?:到期|逾期)|(?:到期|逾期).*疫苗',q) and not re.search(r'提醒|通知|修改|更新|設定|任務|報表|統計|已施打日期',q):
        m=re.search(r'(\d{1,4})\s*天',q)
        days=int(m[1]) if m else 30
        if days>366:return reply('請指定 366 天以內的到期查詢期間。')
        end=(current+timedelta(days=days)).isoformat()
        a=select_target()
        if a is None and re.search(r'[A-Za-z]{2,}',q):
            return reply('找不到指定動物，請提供正確名稱或 #編號。',target=None)
        args=[]
        sql="""SELECT a.id,a.name,v.vaccine_type,v.next_due_date FROM vaccination_records v JOIN animals a ON a.id=v.animal_id
            WHERE a.is_active=1 AND NOT EXISTS(
              SELECT 1 FROM vaccination_records n WHERE n.animal_id=v.animal_id AND n.vaccine_type=v.vaccine_type
              AND (n.administered_date>v.administered_date OR (n.administered_date=v.administered_date AND n.id>v.id)))"""
        exact=bool(a and not m and not re.search(r'逾期|已到期|即將|未來|近期|快到期|最近|哪些',q))
        if exact:
            scope='最新疫苗到期日期'
        elif '逾期' in q:
            sql+=' AND v.next_due_date<?';args.append(current.isoformat());scope='今日以前已逾期'
        elif '已到期' in q:
            sql+=' AND v.next_due_date<=?';args.append(current.isoformat());scope='截至今日已到期'
        else:
            sql+=' AND v.next_due_date BETWEEN ? AND ?';args.extend([current.isoformat(),end]);scope=f'{current.isoformat()} 至 {end} 即將到期（不含逾期）'
        if a:sql+=' AND a.id=?';args.append(a['id'])
        if not manager:sql+=" AND EXISTS(SELECT 1 FROM weekly_tasks t WHERE t.animal_id=a.id AND t.staff_id=? AND t.state!='cancelled')";args.append(staff)
        rows=list(db.execute(sql+' ORDER BY v.next_due_date,a.id',args))
        prefix=(f"{a['name']} #{a['id']}｜" if a else '')
        lines=[prefix+f'{scope}，可查看的疫苗紀錄共 {len(rows)} 筆、{len({r["id"] for r in rows})} 隻動物。']
        lines += [f"{r['name']} #{r['id']} · {r['vaccine_type']} · 到期 {r['next_due_date']}" for r in rows[:20]]
        if len(rows)>20:lines.append('僅列前 20 筆。')
        if not rows:lines.append('沒有符合條件的具日期疫苗紀錄。')
        lines.append('沒有日期的疫苗登錄無法推算到期；請依實際醫療紀錄核對。')
        return reply('\n'.join(lines),[link('/health' if manager else '/','健康行政核對' if manager else '個人工作台')],sources=['疫苗紀錄（每隻動物、每類型最新一筆）'],target=a['id'] if a else None)
    if not how and re.search(r'逾期|過期|超過期限',q) and re.search(r'任務|工作|待辦',q) and not re.search(r'提醒|通知|取消|建立|新增|修改|統計|報表|昨天|明天|上週|下週',q):
        args=[current.isoformat()]
        sql="""SELECT t.task_id,t.label,t.day,t.start,t.state,t.priority,t.due,t.staff_id,s.name AS staff_name,a.name,a.id
            FROM weekly_tasks t JOIN animals a ON a.id=t.animal_id LEFT JOIN staff s ON s.id=t.staff_id
            WHERE a.is_active=1 AND t.state IN ('pending','in_progress') AND t.due<?"""
        if not manager:sql+=' AND t.staff_id=?';args.append(staff)
        a=select_target()
        if a:sql+=' AND t.animal_id=?';args.append(a['id'])
        rows=list(db.execute(sql+' ORDER BY t.due,t.priority,t.task_id',args))
        lines=[f'截至 {current.isoformat()}，期限早於今日且未完成的任務共 {len(rows)} 項。']
        if not re.search(r'幾項|多少',q):
            lines.extend(f"{r['name']} #{r['id']} · {task_line(r)} · 期限 {r['due']}" for r in rows[:20])
        if len(rows)>20:lines.append('僅列前 20 項。')
        return reply('\n'.join(lines),[link('/resources' if manager else '/','資源配置' if manager else '個人工作台')],sources=['任務期限及狀態'],target=a['id'] if a else None)
    if not how and re.search(r'異常|問題',q) and re.search(r'未結案|還沒結案|尚未結案|待處理|未解決|還沒解決',q) and not re.search(r'任務|建立|新增|回報|更正|修改|提醒|通知|報表|統計|昨天|明天|上週|下週',q):
        sql="""SELECT i.task_id,i.animal_id,i.note,a.name,t.label,r.reported_at
            FROM weekly_issues i JOIN animals a ON a.id=i.animal_id JOIN weekly_tasks t ON t.task_id=i.task_id
            LEFT JOIN weekly_reports r ON r.task_id=i.task_id WHERE i.resolved_at IS NULL AND a.is_active=1"""
        args=[]
        if not manager:sql+=' AND t.staff_id=?';args.append(staff)
        a=select_target()
        if a:sql+=' AND a.id=?';args.append(a['id'])
        rows=list(db.execute(sql+' ORDER BY r.reported_at DESC,i.task_id',args))
        lines=[f'可查看的未結案異常共 {len(rows)} 筆。']
        if not re.search(r'多少|幾筆',q):
            for r in rows[:20]:lines.append(f"{r['name']} #{r['animal_id']} · {r['label']} · {(r['reported_at'] or '')[:10]} · {r['note'] or '無備註'}")
        if len(rows)>20:lines.append('僅列前 20 筆。')
        return reply('\n'.join(lines),[link('/resources' if manager else '/','資源配置' if manager else '個人工作台')],sources=['未結案照護異常'],target=a['id'] if a else None)
    if not how and re.search(r'在所|收容|入所|待在',q) and re.search(r'超過|至少|大於',q) and re.search(r'哪些|多少|幾隻|列出|名單',q) and not re.search(r'提醒|通知|任務|統計|報表|新增|修改',q):
        match=re.search(r'(?:超過|至少|大於)\s*(\d{1,5})\s*天',q)
        if match:
            n=int(match[1]);cutoff=(current-timedelta(days=n)).isoformat();op='<=' if '至少' in q else '<'
            args=[cutoff];sql='SELECT id,name,intake_date FROM animals WHERE is_active=1 AND intake_date'+op+'?'
            if not manager:sql+=" AND EXISTS(SELECT 1 FROM weekly_tasks t WHERE t.animal_id=animals.id AND t.staff_id=? AND t.state!='cancelled')";args.append(staff)
            rows=list(db.execute(sql+' ORDER BY intake_date,id',args))
            lines=[f'以 {current.isoformat()} 計算，符合在所{"至少" if op=="<=" else "超過"} {n} 天的動物共 {len(rows)} 隻。']
            if not re.search(r'多少|幾隻',q):
                lines += [f"{r['name']} #{r['id']} · 入所 {r['intake_date']}" for r in rows[:20]]
            if len(rows)>20:lines.append('僅列前 20 隻。')
            return reply('\n'.join(lines),[link('/animals','動物列表')],sources=['在所動物入所日期'],target=None)
    if not how and re.search(r'已接種|已施打',q) and re.search(r'缺少日期|沒有日期|無日期|缺日期',q) and re.search(r'哪些|多少|幾隻|列出|名單',q):
        sql="""SELECT id,name FROM animals WHERE is_active=1 AND vaccinated='yes'
            AND NOT EXISTS(SELECT 1 FROM vaccination_records v WHERE v.animal_id=animals.id AND v.administered_date IS NOT NULL AND v.administered_date!='')"""
        args=[]
        if not manager:sql+=" AND EXISTS(SELECT 1 FROM weekly_tasks t WHERE t.animal_id=animals.id AND t.staff_id=? AND t.state!='cancelled')";args.append(staff)
        rows=list(db.execute(sql+' ORDER BY id',args))
        lines=[f'疫苗登錄為已接種，但沒有具日期紀錄的在所動物共 {len(rows)} 隻。']
        if not re.search(r'多少|幾隻',q):lines.extend(f"{r['name']} #{r['id']}" for r in rows[:20])
        lines.append('不能由登錄狀態推算日期，請核對原始紀錄。')
        return reply('\n'.join(lines),[link('/health' if manager else '/','健康行政核對' if manager else '個人工作台')],sources=['疫苗登錄及日期紀錄'],target=None)
    if not how and re.search(r'任務|工作|待辦',q) and re.search(r'哪些|有什麼|有沒有|多少|幾項|清單|列出|還有',q) and not re.search(r'安排|指派|建立|新增|回報紀錄|員工|工時|報表|統計|緊急|優先|下一|最急',q):
        a=select_target()
        if a:
            temporal,explicit=ci.dates(q,current)
            tasks=own_tasks(a['id'],True)
            if re.search(r'未完成|還沒|尚未|待辦|待完成|沒做',q):tasks=[t for t in tasks if t['state'] in ('pending','in_progress')]
            elif re.search(r'已完成|做完|完成了',q):tasks=[t for t in tasks if t['state']=='done']
            if explicit:tasks=[t for t in tasks if (t['day'] or t['due']) and temporal['start']<=(t['day'] or t['due'])<=temporal['end']]
            if temporal['period']!='all_day':
                tasks=[t for t in tasks if t['start'] is not None and (t['start']<48 if temporal['period']=='morning' else t['start']>=48)]
            lines=[f"{a['name']} #{a['id']}：可查看的符合條件任務共 {len(tasks)} 項。"]
            if not re.search(r'多少|幾項',q):lines.extend(task_line(t) for t in tasks[:12])
            if len(tasks)>12:lines.append('僅列前 12 項。')
            return reply('\n'.join(lines),[link('/resources' if manager else '/','資源配置' if manager else '個人工作台')],sources=['動物 #'+str(a['id']),*[f"任務 {t['task_id']}" for t in tasks[:12]]],target=a['id'])
    return None
