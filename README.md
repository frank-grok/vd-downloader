# ⬇️ VD Downloader

link ချပေးရုံနဲ့ video download ရတဲ့ webapp — RedNote (小红书), Douyin, TikTok,
Bilibili, Weibo, YouTube, Facebook, Instagram, X, Pinterest...

## ဘယ်လိုအလုပ်လုပ်လဲ

Engine နှစ်မျိုးနဲ့:

1. **yt-dlp engine** — TikTok, YouTube/Shorts, Facebook, Instagram, X, Pinterest.
   ဆာဗာပေါ်မှာ yt-dlp တိုက်ရိုက် run တယ်။
   YouTube က datacenter IP ကို bot-check လုပ်လို့ android/ios client args နဲ့
   ယူတယ် (Shorts ဆို 360p ရတတ်တယ်); yt-dlp မရရင် parse API ကို fallback ယူတယ်။
2. **parse-API engine** — RedNote, Douyin, Bilibili, Weibo, Kuaishou။
   ဒီ China platform တွေက datacenter IP (Render လို) ကို security wall ချထားလို့
   ဆာဗာက တိုက်ရိုက်ယူမရဘူး။ ဒါကြောင့် ပြင်ပ 解析 API (`PARSE_API`) ကနေတစ်ဆင့်
   video直链 ယူပြီးမှ ဆာဗာက download ဆွဲ၊ ဖုန်းကို ပြန်ပို့ပေးတယ်။

## Render ပေါ် တင်နည်း

1. ဒီ folder ကို GitHub repo အသစ်တစ်ခု push လုပ်
2. [Render](https://render.com) → New → Web Service → repo ရွေး
   (render.yaml ပါပြီးသား — Build/Start command အလိုလိုဖြည့်ပေးမယ်)
3. Environment → Add:
   - `DL_TOKEN` = ကိုယ်ကြိုက်တဲ့ စကားဝှက် (မထားရင် လူတိုင်းသုံးလို့ရတယ်)
4. Deploy → ရလာတဲ့ URL ကို ဖုန်း browser မှာ ဖွင့်
5. Webapp ရဲ့ ⚙️ ဆက်တင်မှာ token ထည့် (မှတ်ထားပေးတယ်)

> Render free plan က 15 မိနစ် မသုံးရင် အိပ်သွားတယ် — ပထမဆုံး ဖွင့်ရင်
> စက္ကန့် 30-60 လောက် "ဆာဗာ နိုးနေတုန်း" ပြပြီး ပြန်နိုးလာမယ်။

## သုံးနည်း

1. RedNote/TikTok/... app ထဲက video → Share → Copy Link
2. webapp မှာ link ကပ် → 🔍 စစ်ဆေးရန်
3. cover + title ပေါ်လာရင် အရည်အသွေး ရွေး → ⬇️ ဒေါင်းလုဒ်
4. RedNote photo-note ဆိုရင် 🖼️ zip နဲ့ ဒေါင်းလုဒ် button ပေါ်မယ်

## Env vars

| var | default | ရှင်းပြချက် |
|---|---|---|
| `DL_TOKEN` | _(empty)_ | ထားရင် app သုံးတိုင်း token လိုတယ် |
| `PARSE_API` | `https://www.yhqsj.cn/api/short_videos.php?url=` | RedNote/Douyin/Bilibili 用 解析 API။ သေသွားရင် ဒီ format (`?url=` + JSON `{code, data:{url,title,cover}}`) နဲ့ညီတဲ့ API အသစ် လဲထည့် |
| `MAX_MB` | `500` | တစ်ဖိုင်ကို အများဆုံး MB |
| `YTDLP_EXTRA_ARGS` | _(empty)_ | လိုရင် yt-dlp command မှာ ထည့်မယ့် args (ဥပမာ proxy နောက်က စမ်းရင် `--no-check-certificate`) |

## Debug

`/api/resolve?debug=1` — parse API ရဲ့ အဖြေအတိအကျ ပြန်ပေးတယ်
(ဘာကြောင့်မရလဲ စစ်ဖို့)။

## Local run

```bash
pip install -r requirements.txt
python server.py   # http://localhost:8080
```

## သတိ

- ကိုယ်ပိုင်သုံးဖို့ပါ။ သူများအကြောင်းအရာ ခိုးယူ re-upload လုပ်တာမျိုး မလုပ်ပါနဲ့။
- 解析 API တွေက အလကား service တွေ — တစ်ခါတလေ သေတတ်/နှေးတတ်တယ်။
  မရရင် link အသစ်ကူးပြီး ပြန်စမ်း၊ ဒါမှမဟုတ် `PARSE_API` ကို နောက် API နဲ့ လဲ။
