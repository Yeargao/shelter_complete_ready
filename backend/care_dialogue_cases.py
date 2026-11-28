"""Held-out authored conversations; not imported by runtime intent recognition.
Each tuple: task, employee wording, expected outcome code, expected next task.
The HTTP suite asks for the next step, reports, confirms, and checks database changes.
"""
DIALOGUES=[
 ('健康狀態待確認','身體都正常','healthy',None),
 ('健康狀態待確認','檢查出身體不適','sick','優先確認健康狀況'),
 ('健康狀態待確認','發現有傷口','injured','優先確認健康狀況'),
 ('優先確認健康狀況','傷勢完全復原了','recovered',None),
 ('優先確認健康狀況','傷口仍未痊癒','not_recovered','健康問題追蹤'),
 ('健康問題追蹤','病已經痊癒了','recovered',None),
 ('健康問題追蹤','傷勢略有改善但尚未痊癒','improving','健康問題追蹤'),
 ('健康問題追蹤','傷勢一直沒有起色','worsening','優先確認健康狀況'),
 ('確認疫苗紀錄','疫苗以前打過','yes','更新疫苗紀錄'),
 ('確認疫苗紀錄','疫苗從來沒有打過','no','疫苗施打'),
 ('疫苗施打','疫苗剛剛打完了','done','更新疫苗紀錄'),
 ('疫苗施打','疫苗本次沒打成','failed','疫苗施打'),
 ('更新疫苗紀錄','疫苗資料都補齊了','done','疫苗施打'),
 ('確認驅蟲紀錄','以前驅過蟲','yes','更新驅蟲狀態'),
 ('確認驅蟲紀錄','驅蟲從來沒做過','no','基礎驅蟲'),
 ('基礎驅蟲','驅蟲順利做完了','done','更新驅蟲紀錄'),
 ('基礎驅蟲','驅蟲這次沒做成','failed','基礎驅蟲'),
 ('更新驅蟲狀態','驅蟲狀態已經改好了','done',None),
 ('更新驅蟲紀錄','驅蟲檔案都寫好了','done',None),
 ('評估絕育安排','早就做過結紮','already','更新絕育狀態'),
 ('評估絕育安排','獸醫確認目前可以接受絕育','suitable','絕育手術'),
 ('評估絕育安排','獸醫確認現在不宜做絕育','defer','評估絕育安排'),
 ('絕育手術','手術順利完成了','done','更新絕育狀態'),
 ('絕育手術','絕育手術本次沒做完','incomplete','評估絕育安排'),
 ('更新絕育狀態','絕育登錄已經填好了','done',None),
 ('術後健康追蹤','術後完全恢復正常了','recovered',None),
 ('術後健康追蹤','術後仍未恢復','not_recovered','術後健康追蹤'),
 ('術後健康追蹤','術後發現不對勁','abnormal','優先確認健康狀況'),
]
