# 視覺系統與人物動作

本風格的識別點是像素人物／場地加上清晰的實體卡牌質感。先看 [完成版參考](../assets/style-reference.jpg)，保留構圖語言，換掉新案角色與劇情。

## 版面與層級

預設畫布 1080×1920；像素場景可在 540×960 繪製後以 nearest-neighbor 放大 2 倍。卡牌、需要清晰的標題及真人資料畫面另在最終解析度合成。

| 區域 | 540×960 邏輯座標參考 |
| --- | --- |
| 標題 | y 24–76 |
| 回合與敵方 HP | y 88–152 |
| 主戰場 | x 12–528、y 162–660 |
| 玩家 HP | y 670–732 |
| 原音字幕／敘事 | y 750–920 |
| 小型戲仿標示 | y 940 附近，避免平台底部覆蓋 |

底色 `#081423`，面板 `#10283a`，玩家青綠 `#41dac9`，敵方紫 `#c284ed`，金色重點 `#f0ce7a`，危機珊瑚紅 `#ff7972`。可隨主題調色，避免每個區塊都同時搶眼。

戰場用透視桌面、怪獸區與魔法陷阱槽，牌堆位於近景側邊。原案例主角左下大、對手右上小；怪獸應位在自己的場區，不蓋人物臉。亮牌可暫壓暗背景，字幕區始終保留對比。

## 真卡與自創卡

- **卡背：** 遊戲王原版要求使用可查核的棕橙螺旋渦流卡背；不要以幾條程序螺旋、橢圓圖案代替。牌堆、抽出卡和大幅手牌背面保持一致。
- **指定真卡：** 查官方卡片資料及可用實卡圖，保存版本。經典插圖再版不等於最早初版；不要把 2004 年掃描稱為 1999 年初版。原始標記／浮水印不靠生成方式抹掉。
- **自創卡：** 保留真卡比例、標題區、卡種框、主插圖和效果欄。插圖採有體積、景深、材質和光線的幻想寫實繪畫；不要只用幾何硬幣／摩天輪線條圖。
- 自創卡面上的小字可由程式在清晰圖層排版；AI 生成字有錯就修正，不能讓錯名進最終特寫。自創卡標為戲仿，避免把新造效果說成官方卡。
- 卡圖 resize 用 LANCZOS、旋轉可用 BICUBIC，維持原比例；切勿先把高解析卡縮入 540×960 場景再放大。手牌特寫維持足以看清卡名的停留時間。

自創卡插圖提示詞骨架：

> Create a detailed fantasy trading-card illustration for [card concept]. Painterly realism, dimensional materials, dramatic but readable lighting, intricate environmental detail, one clear focal point. [Concrete setting and symbols]. No pixel art, no flat infographic, no UI or lettering inside the artwork. Compose for the square illustration window of a portrait spell card.

框與文字可程式組版；若要生成整張卡，另明確指定精確繁體卡名、卡種、版式，生成後逐項看圖驗字。原生 ImageGen 用於圖像創作／修圖，程式用於排版與合成。

## 人物與怪獸

先用來源代表幀確認臉、髮型、服裝和持牌方向，再生成帶 Alpha 的動作圖。玩家背側、對手前側，雙方朝向戰場；臉可偏動漫像素，但應可辨識。

常用八姿勢只是方便排版：待機持牌、蓄勢／說話、出牌／發動、受擊、低血量、抽牌／勝利、特殊效果準備、特殊效果空中／結果。按角色實際事件改姿勢表，不為八格湊無用動作。怪獸有自己的待機、蓄力、攻擊、受擊、消失等姿勢。

圖集提示詞骨架：

> Transparent RGBA sprite atlas, [columns] by [rows], consistent [character] identity, costume, scale and pixel-art finish. [Player three-quarter back view facing right / opponent three-quarter front view facing left]. Full body including fingertips, held cards and shoes in every pose. Clear transparent gutters; no pose touches another. Pose order: [explicit list]. No labels, captions, border, ground, detached extra limbs, duplicates or background.

生成後檢查實際 Alpha，不把棋盤格背景當透明。站姿高度與腳底錨點固定，同一人物所有姿勢沿用同一比例；躺下或跳躍不能依各自外框高度重新拉大。以完整連通範圍註冊，伸出的手跨過虛擬網格時要保留。

## 浮手／裁切修正

只對外框裁切不夠：某姿勢的外框可能包含鄰格的手。使用 `scripts/sprite_tools.py` 的 `isolate_pose(sheet, bounds, seed_points)`，種子是**整張圖集座標**，位於人工確認的身體／道具不透明區。

```python
from sprite_tools import isolate_pose
pose, audit = isolate_pose(sheet_rgba, bounds=(x0, y0, x1, y1),
                           seed_points=[(body_x, body_y)])
# pose 只用於合成；保留原始 ImageGen 圖集。
```

先在全圖標記連通元件，再於範圍內只保留選定元件和一圈原始半透明邊緣。合法分離道具、特效或獨立手勢可加多個種子；不能一律「只保留最大塊」。種子落透明區、身體延伸到外框以外或兩個姿勢黏在一起時，停止自動裁切並重新註冊／生圖。

這個函式解決合成取樣問題，不會修正圖本身多手指、畸形手或缺肢。來源圖的解剖問題用 ImageGen 針對該姿勢修正。
