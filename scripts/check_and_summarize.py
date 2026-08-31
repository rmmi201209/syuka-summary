import os
import sys
import json
import argparse
from datetime import datetime, timezone, timedelta
import requests
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

def check_new_videos(force_video_id=None, check_hours=24):
    """
    yt-dlp를 사용하여 슈카월드 유튜브 채널의 최근 동영상을 탐색합니다.
    force_video_id가 제공되면 감지 과정을 생략하고 강제 진행합니다.
    """
    if force_video_id:
        print(f"[INFO] Forcing processing for Video ID: {force_video_id}")
        return [{"id": force_video_id, "title": "Forced Test Video", "published": datetime.now(timezone.utc).isoformat()}]

    channel_url = "https://www.youtube.com/@syukaworld/videos"
    print(f"[INFO] Fetching video list via yt-dlp from: {channel_url}")
    
    ydl_opts = {
        'extract_flat': 'in_playlist',
        'skip_download': True,
        'playlistend': 5,  # 최근 5개 비디오만 로드
        'quiet': True,
        'no_warnings': True
    }
    
    new_videos = []
    now = datetime.now(timezone.utc)
    check_delta = timedelta(hours=check_hours)
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
            if 'entries' not in info:
                print("[ERROR] No video entries found in channel info.")
                return []
                
            entries = info['entries']
            print(f"[INFO] Successfully fetched {len(entries)} videos via yt-dlp.")
            
            for entry in entries:
                video_id = entry.get('id')
                title = entry.get('title')
                upload_date_str = entry.get('upload_date') # YYYYMMDD 형식
                
                if upload_date_str:
                    try:
                        published_dt = datetime.strptime(upload_date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
                    except Exception:
                        published_dt = now
                else:
                    published_dt = now
                    
                time_diff = now - published_dt
                
                if time_diff <= check_delta:
                    print(f"[NEW] Found recent video: {title} ({video_id}) - Uploaded on {upload_date_str if upload_date_str else 'Unknown'}")
                    new_videos.append({
                        "id": video_id,
                        "title": title,
                        "published": published_dt.isoformat()
                    })
    except Exception as e:
        print(f"[ERROR] Failed to fetch channel videos via yt-dlp: {e}")
        return []
        
    return new_videos

def get_transcript(video_id):
    """
    youtube-transcript-api를 사용하여 한국어 자막 대본을 가져옵니다.
    """
    print(f"[INFO] Fetching transcript for Video ID: {video_id}...")
    try:
        # 우선 한국어('ko') 자막 시도
        # 인스턴스 생성 후 fetch() 사용
        transcript_list = YouTubeTranscriptApi().fetch(video_id, languages=['ko'])
        
        # 타임라인 정보가 포함된 원본 자막 데이터를 요약 시 맥락을 위해 하나의 텍스트로 병합
        full_text = []
        for segment in transcript_list:
            text = segment.text.strip()
            # 타임라인 초 단위를 분:초 형식으로 변환하여 텍스트에 태그처럼 남김 (Gemini가 타임라인 잡기 용이함)
            start_sec = int(segment.start)
            minutes = start_sec // 60
            seconds = start_sec % 60
            timestamp = f"[{minutes:02d}:{seconds:02d}]"
            full_text.append(f"{timestamp} {text}")

        return "\n".join(full_text)
    except Exception as e:
        print(f"[ERROR] Failed to fetch transcript for {video_id}: {e}")
        return None

def summarize_transcript(title, transcript_text):
    """
    Gemini 2.5 Flash API를 활용하여 유튜브 자막을 구조화된 JSON 데이터로 요약합니다.
    """
    print(f"[INFO] Summarizing transcript using Gemini API for: {title}...")
    
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key or gemini_key == "your_gemini_api_key_here":
        print("[ERROR] GEMINI_API_KEY is not configured in .env file.")
        return None

    # google-generativeai SDK 설정
    import google.generativeai as genai
    genai.configure(api_key=gemini_key)

    model = genai.GenerativeModel("gemini-3.6-flash")

    prompt = f"""
너는 아주 유능한 유튜브 영상 요약 에디터이자 경제/시사 전문 뉴스레터 필진이야.
유튜브 영상 제목인 "{title}"과 아래 제공되는 영상의 타임라인별 대본(자막)을 읽고, 독자들이 대본을 직접 읽지 않고도 핵심을 아주 정확하고 깊이 있게 파악할 수 있도록 구조화된 한국어 요약문을 작성해줘.

대본 속의 타임라인 정보(예: [01:23])를 적극 참고하여, 주요 주제가 바뀌는 시점의 정확한 타임라인 정보와 핵심 요약을 짝지어 매칭해줘.
응답은 반드시 정해진 JSON 형식으로만 작성해야 하며, 어떠한 마크다운 백틱(```json)이나 부가 설명 없이 오직 유효한 JSON 문자열로만 응답해야 해.

[대본]
{transcript_text}

[JSON 응답 구조]
{{
  "one_liner": "이 영상 전체 내용을 아우르는 핵심을 찌르는 강렬한 한 줄 요약",
  "keywords": ["주제키워드1", "주제키워드2", "주제키워드3"],
  "chapters": [
    {{
      "title": "첫 번째 세부 주제 (예: 엔비디아 실적 발표와 주가 전망)",
      "timeline": "해당 단락의 대략적인 시작 타임라인 (분:초 형식, 예: 02:15)",
      "content": "이 주제에 대한 상세 내용 요약. 구체적인 수치(퍼센트, 달러, 개수 등), 인용 주장, 배경 상황 및 시사점을 풍부하게 담아서 3~4줄로 명확하게 요약해줘."
    }},
    {{
      "title": "두 번째 세부 주제",
      "timeline": "시작 타임라인 (예: 11:40)",
      "content": "두 번째 주제의 요약..."
    }}
  ],
  "insights": "이 영상이 주는 궁극적인 시사점 및 트렌드 전망에 대한 정리 (3줄 내외)"
}}
"""

    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return response.text
    except Exception as e:
        print(f"[ERROR] Gemini API call failed: {e}")
        return None

def save_to_database(video_id, title, published, summary_str):
    """
    요약본 데이터를 public/data.json에 누적하여 저장합니다.
    """
    data_dir = os.path.abspath("public")
    data_file = os.path.join(data_dir, "data.json")

    # 디렉토리 생성
    os.makedirs(data_dir, exist_ok=True)

    # 기존 데이터 로드
    data_list = []
    if os.path.exists(data_file):
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                data_list = json.load(f)
        except Exception as e:
            print(f"[WARNING] Failed to load existing data.json, starting fresh: {e}")
            data_list = []

    # 중복 저장 방지
    if any(item.get("id") == video_id for item in data_list):
        print(f"[INFO] Video ID {video_id} already exists in database. Skipping saving.")
        return False, None

    try:
        summary_data = json.loads(summary_str)
    except Exception as e:
        print(f"[ERROR] Failed to parse summary string as JSON: {e}")
        print(f"[DEBUG] Raw summary: {summary_str}")
        return False, None

    new_entry = {
        "id": video_id,
        "title": title,
        "published": published,
        "summary": summary_data,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    # 최신 데이터를 배열의 맨 앞에 추가
    data_list.insert(0, new_entry)

    try:
        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(data_list, f, ensure_ascii=False, indent=2)
        print(f"[SUCCESS] Saved summary for {video_id} to public/data.json")
        return True, new_entry
    except Exception as e:
        print(f"[ERROR] Failed to write data.json: {e}")
        return False, None

def main():
    parser = argparse.ArgumentParser(description="Syuka World YouTube Summarizer")
    parser.add_argument("--force", type=str, help="Process a specific video ID instead of monitoring feed")
    parser.add_argument("--hours", type=int, default=24, help="Monitoring check window in hours (default: 24)")
    args = parser.parse_args()

    # 1. 신규 영상 체크
    new_videos = check_new_videos(force_video_id=args.force, check_hours=args.hours)

    if not new_videos:
        print("[INFO] No new videos found.")
        sys.exit(0)

    print(f"[INFO] Processing {len(new_videos)} videos...")
    
    processed_count = 0
    saved_entries = []

    for video in new_videos:
        video_id = video["id"]
        title = video["title"]
        published = video["published"]

        # 2. 자막 대본 추출
        transcript = get_transcript(video_id)
        if not transcript:
            print(f"[SKIP] Transcript not available for video: {title} ({video_id})")
            continue

        # 3. Gemini 요약 수행
        summary_json = summarize_transcript(title, transcript)
        if not summary_json:
            print(f"[SKIP] Summary generation failed for video: {title} ({video_id})")
            continue

        # 4. JSON 파일 저장 (DB)
        success, entry = save_to_database(video_id, title, published, summary_json)
        if success:
            processed_count += 1
            saved_entries.append(entry)

    print(f"[INFO] Batch processing finished. {processed_count} new summaries created.")
    
    # 5. 메일 발송 프로세스를 위해 저장된 데이터 전달 목적으로 임시 출력 남김
    if saved_entries:
        # 이 출력값은 나중에 다른 래퍼 스크립트나 CI/CD 환경에서 감지하여 메일 발송 대상으로 삼을 수 있습니다.
        print(f"[METADATA] NEW_SUMMARIES_COUNT={len(saved_entries)}")

if __name__ == "__main__":
    main()
