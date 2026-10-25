# Google Services Cookie Manager API (Gemini & YouTube)

এটি একটি লাইটওয়েট এবং উচ্চক্ষমতাসম্পন্ন ক্লাউড-রেডি (Railway / Render / Docker) API সার্ভিস, যা **Gemini** এবং **YouTube**-এর জন্য সক্রিয় লগইন কুকিজ সরবরাহ করে।

---

## 🌟 প্রধান বৈশিষ্ট্যসমূহ:
1. **স্মার্ট ভ্যালিডেশন (No Browser Overhead):**
   - কুকিজ ভ্যালিড থাকলে কোনো ব্রাউজার চালু হয় না। শুধু সাধারণ HTTP রিকোয়েস্টে мгновенно (কয়েক মিলিসেকেন্ডে) কুকিজ রিটার্ন করে।
2. **অটো-রিফ্রেশ (Auto-Rotation):**
   - প্রতি রিকোয়েস্টে গুগলের কাছ থেকে নতুন সিকিউরিটি টোকেন (`SIDTS`, `SSID` ইত্যাদি) রিফ্রেশ করে স্বয়ংক্রিয়ভাবে লোকাল ফাইলে আপডেট করে।
3. **স্মার্ট ফলব্যাক (Headless Chromium CDP):**
   - সেশন এক্সপায়ার হলে ব্যাকগ্রাউন্ডে হেডলেস ক্রোম চালু করে নতুন লাইভ কুকিজ সংগ্রহ করে।

---

## 🚀 API এন্ডপয়েন্টস

### ১. Gemini Cookies
```http
GET /get?cookies=gemini
```
**রেসপন্স:**
```json
{
  "service": "gemini",
  "success": true,
  "method": "requests_existing",
  "cookies_count": 35,
  "timestamp": 1792912328,
  "cookies": [
    {
      "name": "SID",
      "value": "g.a000...",
      "domain": ".google.com",
      "path": "/",
      "secure": false,
      "httpOnly": false,
      "expiry": 1795504055
    }
  ]
}
```

### ২. YouTube Cookies
```http
GET /get?cookies=youtube
```
**রেসপন্স:**
```json
{
  "service": "youtube",
  "success": true,
  "method": "requests_existing",
  "cookies_count": 28,
  "timestamp": 1792912328,
  "cookies": [ ... ]
}
```

---

## 🔑 নতুন কোনো Gmail অ্যাকাউন্ট যোগ বা পরিবর্তন করবেন কীভাবে?

ভবিষ্যতে যদি নতুন কোনো Gmail অ্যাকাউন্টের কুকিজ ব্যবহার করতে চান, তবে মাত্র **১টি ফাইল** আপডেট করলেই হবে:

### ফাইল: `seed_cookies.json`

### যেভাবে নতুন অ্যাকাউন্টের কুকিজ সেট করবেন:
1. আপনার ব্রাউজারে যে নতুন Gmail অ্যাকাউন্টটি লগইন আছে, সেখান থেকে কুকিজগুলো JSON আকারে কপি করুন (যেমন: ব্রাউজারের `EditThisCookie` বা `Cookie-Editor` এক্সটেনশন ব্যবহার করে **Export JSON** দিন)।
2. [seed_cookies.json](file:///c:/Users/abc/Downloads/Server%20Copy/render_deploy/seed_cookies.json) ফাইলটিতে নিচের ফরম্যাটে পেস্ট করুন:
   ```json
   {
       "cookies_count": 50,
       "cookies": [
           {
               "name": "SID",
               "value": "আপনার_নতুন_SID_মান",
               "domain": ".google.com",
               "path": "/",
               "secure": false,
               "httpOnly": false,
               "expiry": 1827471643
           },
           {
               "name": "HSID",
               "value": "...",
               "domain": ".google.com",
               "path": "/"
           }
       ]
   }
   ```
3. ফাইলটি সেভ করে গিটহাবে পুশ করে দিন:
   ```bash
   git add seed_cookies.json
   git commit -m "Update account cookies"
   git push origin main
   ```
4. **ব্যাস!** সার্ভার চালু হওয়ামাত্রই এই নতুন কুকিজগুলো দিয়ে স্বয়ংক্রিয়ভাবে Gemini এবং YouTube-এর সেশন সচল রাখবে।
