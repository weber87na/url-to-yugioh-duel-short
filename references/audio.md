# 原音、音效與經典配樂

## 音軌來源與剪輯

分別保存全長 `dialogue.wav`、純 `effects.wav`、`music.wav`，無內容的時間用靜音填補。聲音軌對齊成片 0 秒，避免拿「原片音軌」冒充「剪完的對白」。多來源台詞先按已查核時間軸組成 dialogue，或在合成工具內逐段對齊；下方混音器一個 stem 只接一個來源檔案。

原音不變速、不改聲線；可做必要音量平衡與短邊緣淡化。語音 -17 LUFS、配樂約 -25 至 -23 LUFS、亮牌後略提高，是本案例的起點，不要求所有來源照抄。不要先把每種音軌 peak normalize 到同一音量。

選曲時先確認使用者有無指定。沿用本次經典對戰風格可參考 [案例原曲](proven-case.md#音樂剪法)，但角色、曲目與剪點均可更換。優先查官方曲目與可正常取得的音源，區分原曲、翻奏和重混。保存來源頁與版本，不把下載的有損音訊轉 WAV 後稱為無損原盤。

以強起音／主題進入點對上亮牌或發動。原曲前奏可重用並 crossfade；抽牌前短停頓能隱藏剪接。用公式 `source_start = source_cue - (output_cue - output_start)` 定位；播放速率維持 1。音樂若只有波形分析，記錄為訊號剪點，不宣稱已耳辨主旋律。

## 台詞 duck 與動作音效

每段語音都列 duck interval，包含短卡名、對手台詞和最後反擊。建議提前 100–150 ms 下降，句尾後 200–300 ms 恢復；gain 0.12 約為 -18.4 dB，可依素材調整，確認短句不被遮住。

持牌／發動／翻牌／HP ticks／場地水聲等 FX 自行合成或使用已確認素材。FX 不應混入可辨識舊背景樂；語音期間過響的 FX 另外壓低。此混音器的 duck 只作用於 music，FX 時間包絡須在 effects stem 或各 segment 的 gain／fade 中處理。

FFmpeg `amix normalize=0` 保留手動音量比例，最後 limiter 不要自動補大整體音量，使用 `latency=1` 補償 lookahead。AAC 重新編碼可能改峰值，因此驗最終檔，不只驗 WAV。

## 混音器

```powershell
python -X utf8 "技能目錄/scripts/mix_audio.py" "工程目錄/mix.json"
```

所有路徑相對於 `mix.json`；不受 shell 的 cwd 影響。影片與三 stem 可完全分離。以下是 **10 秒示意設定**，來源必須實際足夠長，原音須已對齊；依本案改路徑、時長與剪點。

```json
{
  "duration_s": 10,
  "video": "output/picture.mp4",
  "output": "output/final_v2.mp4",
  "dialogue": "audio/dialogue.wav",
  "effects": "audio/effects.wav",
  "music": {
    "source": "source/score.wav",
    "gain": 0.35,
    "segments": [
      {"source_start": 0, "output_start": 0, "duration": 4,
       "fade_in": 0.1, "fade_out": 0.2},
      {"source_start": 10, "output_start": 5, "duration": 5,
       "fade_in": 0.1, "fade_out": 0.8}
    ],
    "duck_intervals": [
      {"start": 1, "end": 2.5, "gain": 0.12, "attack": 0.15, "release": 0.25},
      {"start": 7, "end": 8, "gain": 0.12, "attack": 0.15, "release": 0.25}
    ]
  }
}
```

欄位規則：

- 必填 `duration_s`、`video`、`output`；輸出支援 MP4／MOV／MKV，來源影片長度須涵蓋目標片長，最多允許一幀誤差。
- `dialogue/effects/music` 可用路徑字串、null，或 `{source, gain, segments}`。null／省略為靜音，沒有 `segments` 則從來源 0 秒播放，短檔補靜音，長檔截到目標時長；空陣列就是靜音。
- segment 必填 `source_start`、`output_start`、`duration`；可選 `gain`（預設 1）、`fade_in/out`（預設 0）。單位均為秒，gain 是線性值；每段原速播放。
- segments 相疊會相加，只有明列淡出與淡入才是 crossfade。若新段在舊段結束前 0.25 秒開始，兩段分別設定 0.25 秒淡出／淡入。
- music 的 duck 平台是 `[start,end]`，attack 往前延伸、release 往後延伸；重疊區取最小 gain，不相乘。
- 預設不覆寫；經確認重做可加 `--overwrite`，仍禁止覆蓋來源檔或設定檔。只傳入本次想保留的聲音，來源影片原有音軌會被捨棄。

輸出包含影片、`影片名.mix_manifest.json`，以及 `影片名_stems/` 的 dialogue／effects／music／mix WAV。中間軌為 48 kHz stereo float32 PCM，保留限幅前動態餘裕；最終 AAC 192k。視訊採 stream-copy，不重新生成影格。工具不會判斷原音講者，也不會自動選曲。

## 驗證換曲

以同樣時長輸出後比較壓縮視訊 bitstream：

```powershell
ffmpeg -v error -i "原成片.mp4" -map 0:v:0 -c copy -f hash -hash sha256 -
ffmpeg -v error -i "新成片.mp4" -map 0:v:0 -c copy -f hash -hash sha256 -
```

如刻意改總長，整段雜湊自然不同，須改驗所保留段落。混音後核對四類資訊：原音完整與同步、duck 在所有台詞生效、沒有殘留舊 BGM、輸出無削波與解碼錯誤。可將最終音訊對原 dialogue 做相關係數輔助定位，但不要把單一數字門檻當成主觀聽感保證。
