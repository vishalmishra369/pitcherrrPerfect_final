from flask import Flask, render_template, request, Response, jsonify
import requests
import google.generativeai as genai
import os
from dotenv import load_dotenv
import time
from num2words import num2words
import re
import statsapi
import pyttsx3
from google.cloud import translate_v2 as translate_client # Import Translation Client

load_dotenv()
app = Flask(__name__)

genai.configure(api_key=os.getenv("API_KEY"))

default_prompt = """You are a passionate baseball commentator bringing the game to life. Given the following details:
Teams playing: {teams}, Venue: {venue}, Date: {date}, Inning-by-inning breakdown: {inning_plays}, Play descriptions: {play_descriptions}, Final score: {final_score}.
Deliver an energetic, concise highlight reel focusing on game-changing moments, home runs with extra flair, clutch plays, final result drama. Use authentic baseball terminology and maintain high energy. Keep it under 3-4 key moments. End with the final score and what this means for both teams. Include Key play by play moments within the highlights of the game, home runs, cluth play, final result drama.
"""

generation_config = {
    "temperature": 0.7, # Lowered temperature for more consistent output
    "top_p": 0.95,
    "top_k": 64,
    "max_output_tokens": 8192,
    "response_mime_type": "text/plain",
}

model = genai.GenerativeModel(
    model_name="gemini-1.5-pro",
    generation_config=generation_config,
    system_instruction=default_prompt + " "
)
import json
def stream_gemini_response(user_input, game_pk):
    try:
        chat_session = model.start_chat()
        response = chat_session.send_message(user_input, stream=True)
        
        has_yielded = False
        for chunk in response:
            has_yielded = True
            yield f"data: {chunk.text}\n\n"
        
        if not has_yielded:
            game_details = get_essential_game_info(game_pk)
            fallback = generate_fallback_commentary(game_details)
            # Send a single, formatted fallback response
            yield f"data: {'\\n'.join(fallback)}\n\n"
            
    except Exception as e:
        game_details = get_essential_game_info(game_pk)
        fallback = generate_fallback_commentary(game_details)
        # Send a single, formatted fallback response
        yield f"data: {'\\n'.join(fallback)}\n\n"

# --- MLB API Data Fetching ---
MLB_API_URL = 'https://statsapi.mlb.com/api/v1/schedule'
def fetch_game_data(game_pk):
    response = requests.get(f"{MLB_API_URL}?gamePk={game_pk}")
    game_info = response.json().get("dates", [])[0].get("games", [])[0]

    return {
        'home_team': game_info['teams']['home']['team']['name'],
        'away_team': game_info['teams']['away']['team']['name'],
        'home_score': game_info['teams']['home'].get('score', 0),
        'away_score': game_info['teams']['away'].get('score', 0),
        'game_date': game_info['gameDate'],
        'venue': game_info.get('venue', {}).get('name', 'N/A'),
        'home_team_logo': f'https://www.mlbstatic.com/team-logos/{game_info["teams"]["home"]["team"]["id"]}.svg',
        'away_team_logo': f'https://www.mlbstatic.com/team-logos/{game_info["teams"]["away"]["team"]["id"]}.svg',
        'status': game_info.get('status', {}).get('detailedState', 'N/A')
    }

# --- Essential Game Info ---
def get_essential_game_info(game_pk):
    game_data = fetch_game_data(game_pk)
    teams_and_score = {
        'matchup': f"{game_data['away_team']} vs {game_data['home_team']}",
        'final_score': f"{game_data['away_score']} - {game_data['home_score']}",
        'venue': game_data['venue'],
        'date': game_data['game_date']
    }

    game = statsapi.get('game', {'gamePk': game_pk})
    all_plays = game.get('liveData', {}).get('plays', {}).get('allPlays', [])
    inning_plays = []
    play_descriptions = [] # List to store play descriptions
    for play in all_plays:
        if play.get('about', {}).get('isComplete', False):
            inning_plays.append({
                'inning': f"{'Top' if play['about']['halfInning'] == 'top' else 'Bottom'} {play['about']['inning']}",
                'description': play['result'].get('description', ''),
                'score': f"{play['result'].get('awayScore', 0)}-{play['result'].get('homeScore', 0)}"
            })
            play_descriptions.append(play['result'].get('description', '')) # Add play description

    return {
        'game_info': teams_and_score,
        'plays': inning_plays,
        'play_descriptions': play_descriptions, # Include play descriptions in returned data
        'game_data': game_data
    }

# --- Fallback Commentary Generator ---
def generate_fallback_commentary(game_data):
    away_score, home_score = map(int, game_data['game_info']['final_score'].split(' - '))
    teams = game_data['game_info']['matchup'].split(' vs ')
    winning_team = teams[0] if away_score > home_score else teams[1]

    commentary = [
        f"⚾ WELCOME TO {game_data['game_info']['venue'].upper()}! ⚾",
        f"Today's matchup: {game_data['game_info']['matchup']} on {game_data['game_info']['date']}",
        "=" * 50
    ]

    current_inning = ""
    for play in game_data['plays']:
        if play['inning'] != current_inning:
            current_inning = play['inning']
            commentary.append(f"\n🎯 {current_inning.upper()}")

        commentary.append(f"• {play['description']}")
        commentary.append(f"Score Update: {play['score']}")

    commentary.extend([
        "\n🏆 FINAL WRAP",
        "=" * 50,
        f"{winning_team} takes this one!",
        f"Final Score: {game_data['game_info']['final_score']}",
        "\n📊 GAME HIGHLIGHTS",
        f"Venue: {game_data['game_info']['venue']}",
        f"Matchup: {game_data['game_info']['matchup']}",
        f"Date: {game_data['game_info']['date']}"
    ])

    return commentary

# --- Text Cleaning and Number Conversion ---
def convert_numbers_to_words(text):
    words = text.split()
    for i, word in enumerate(words):
        cleaned_word = word.replace('-', '').replace('.', '')
        if cleaned_word.isdigit():
            words[i] = num2words(int(cleaned_word))
        elif '-' in word and all(part.isdigit() for part in word.split('-')):
            nums = word.split('-')
            words[i] = f"{num2words(int(nums[0]))} to {num2words(int(nums[1]))}"
    return ' '.join(words)

import pyttsx3
from googletrans import Translator
import os

# Initialize translator and TTS engine
translator = Translator()
engine = pyttsx3.init()

def setup_voice_options():
    voices = engine.getProperty('voices')
    voice_options = {
        'male': [v for v in voices if 'male' in v.name.lower()][0],
        'female': [v for v in voices if 'female' in v.name.lower()][0]
    }
    return voice_options

def speak(text, language='en', gender='female', output_dir='static/audio'):
    os.makedirs(output_dir, exist_ok=True)
    filename = f"speech_{hash(text)}_{language}_{gender}.wav"
    audio_path = os.path.join(output_dir, filename)
    
    try:
        # Translate if needed
        if language != 'en':
            translated = translator.translate(text, dest=language)
            text = translated.text
        
        # Set voice properties
        voices = setup_voice_options()
        engine.setProperty('voice', voices[gender].id)
        engine.setProperty('rate', 150)
        engine.setProperty('volume', 1.0)
        
        # Save to file
        engine.save_to_file(text, audio_path)
        engine.runAndWait()
        
        return {'audio_url': f'/static/audio/{filename}', 'text': text}
    except Exception as e:
        print(f"TTS error: {e}")
        return {'error': str(e)}

@app.route('/speak', methods=['POST'])
def speak_route():
    text = request.form.get('text', '')
    language = request.form.get('language', 'en')
    gender = request.form.get('gender', 'female')
    
    result = speak(text, language, gender)
    return jsonify(result)

# --- Main Routes ---
@app.route('/')
def index():
    return render_template('c.html')

@app.route('/stream_ai_commentary/<game_pk>')
def stream_ai_commentary(game_pk):
    language = request.args.get('language', 'en')
    game_details = get_essential_game_info(game_pk)
    
    try:
        prompt_data = {
            'teams': game_details['game_info']['matchup'],
            'venue': game_details['game_info']['venue'],
            'date': game_details['game_info']['date'],
            'inning_plays': "\n".join(f"{p['inning']}: {p['description']} (Score: {p['score']})" for p in game_details['plays']),
            'play_descriptions': "\n".join(game_details['play_descriptions']),
            'final_score': game_details['game_info']['final_score']
        }
        
        user_input = default_prompt.format(**prompt_data)
        return Response(stream_gemini_response(user_input,game_pk), mimetype='text/event-stream')
        
    except Exception:
        # Direct fallback if prompt formatting fails
        commentary = generate_fallback_commentary(game_details)
        return Response(f"data: {' '.join(commentary)}\n\n", mimetype='text/event-stream')

@app.route('/get_ai_commentary/<game_pk>')
def get_ai_commentary(game_pk):
    game_details = get_essential_game_info(game_pk)
    commentary = generate_fallback_commentary(game_details)
    return jsonify({'commentary': commentary,
                    'game_info': game_details['game_info']})


@app.route('/game/<game_pk>')
def game_highlights(game_pk):
    game_details = fetch_game_data(game_pk)
    return render_template('c.html', game_data=game_details, game_pk=game_pk)


if __name__ == '__main__':
    app.run(debug=True)



import statsapi
import google.generativeai as genai
import os
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

genai.configure(api_key=os.getenv("API_KEY"))

defaultprompt = """You are a passionate baseball commentator bringing the game to life. Given the following details:

Teams playing
Venue and date
Inning-by-inning breakdown
Play descriptions
Final score
Deliver an energetic, concise highlight reel focusing on:

Game-changing moments
Home runs with extra flair
Clutch plays
Final result drama
Record-breaking achievements
Use authentic baseball terminology and maintain high energy. Keep it under 3-4 key moments. End with the final score and what this means for both teams.

Example style: 'Bottom of the 8th, bases loaded, Martinez steps up - CRACK! That ball is GONE! A grand slam that brought the crowd to their feet and changed everything!'"""

# Create the model
generation_config ={
"temperature": 2,
"top_p": 0.95,
"top_k": 64,
"max_output_tokens": 8192,
"response_mime_type": "text/plain",
}

model = genai.GenerativeModel(
model_name="gemini-1.5-pro",
generation_config=generation_config,
system_instruction=defaultprompt + " " 
)

def gemini_chat(user_input):
  try:
    chat_session = model.start_chat()
    response = chat_session.send_message(user_input)

    # Simulate streaming by printing output with a small delay
    for chunk in response.text.split(" "):
      print(chunk, end=" ", flush=True)
      time.sleep(0.1)  # Adjust delay as needed

  except Exception as e:
    print(f"Error during chat: {e}")
    return "An error occurred. Please try again."

MLB_API_URL = 'https://statsapi.mlb.com/api/v1/schedule'

import requests
from flask import render_template
def game_details(game_pk):
    response = requests.get(f"{MLB_API_URL}?gamePk={game_pk}")
    game_info = response.json().get("dates", [])[0].get("games", [])[0]
    
    game_data = {
        'home_team': game_info['teams']['home']['team']['name'],
        'away_team': game_info['teams']['away']['team']['name'],
        'home_score': game_info['teams']['home'].get('score', 0),
        'away_score': game_info['teams']['away'].get('score', 0),
        'game_date': game_info['gameDate'],
        'venue': game_info.get('venue', {}).get('name', 'N/A'),
        'home_team_logo': f'https://www.mlbstatic.com/team-logos/{game_info["teams"]["home"]["team"]["id"]}.svg',
        'away_team_logo': f'https://www.mlbstatic.com/team-logos/{game_info["teams"]["away"]["team"]["id"]}.svg',
        'status': game_info.get('status', {}).get('detailedState', 'N/A')
    }
    
    highlights_data = extract_highlights(game_pk)
    video_highlights = fetch_video_highlights(game_pk)

    # Initialize running scores
    running_away_score = 0
    running_home_score = 0

    # Process each highlight
    for highlight in highlights_data:
        # Update scores based on the play result
        if 'scores' in highlight.get('description', '').lower():
            if 'home' in highlight.get('description', '').lower():
                running_home_score += 1
            else:
                running_away_score += 1
        
        # Add current scores to highlight
        highlight['away_score'] = running_away_score
        highlight['home_score'] = running_home_score
        highlight['time'] = highlight['time'][11:19] if isinstance(highlight['time'], str) else highlight['time']

    return render_template('GameHighlights.html', 
                         game_pk=game_pk,
                         game_data=game_data,
                         highlights_data=highlights_data, 
                         video_highlights=video_highlights,
                         previous_away_score=0,
                         previous_home_score=0)


def extract_highlights(game_pk):
    highlights = []
    try:
        # Get live game data
        game = statsapi.get('game', {'gamePk': game_pk})
        all_plays = game.get('liveData', {}).get('plays', {}).get('allPlays', [])
        
        for play in all_plays:
            if play.get('about', {}).get('isComplete', False):
                result = play.get('result', {})
                about = play.get('about', {})
                
                highlight = {
                    'description': result.get('description', ''),
                    'score': f"Away: {result.get('awayScore', 0)}, Home: {result.get('homeScore', 0)}",
                    'inning': f"{'Top' if about.get('halfInning') == 'top' else 'Bottom'} of the {about.get('inning')} inning",
                    'time': about.get('endTime', '')
                }
                highlights.append(highlight)
                
    except Exception as e:
        print(f"Error extracting highlights: {e}")
    
    return highlights


def fetch_video_highlights(game_pk):
    video_highlights = []
    
    # Get raw highlights data
    raw_highlights = statsapi.game_highlights(game_pk)
    
    # Split the raw text into lines
    lines = raw_highlights.split('\n')
    
    current_title = None
    current_description = None
    
    for line in lines:
        # Skip empty lines
        if not line.strip():
            continue
            
        # Check if line contains video URL
        if line.startswith('https://') and line.endswith('.mp4'):
            if current_title and current_description:
                video_highlights.append({
                    'title': current_title,
                    'description': current_description,
                    'video_url': line.strip()
                })
            current_title = None
            current_description = None
            
        # Check if line contains title (they typically end with duration in parentheses)
        elif '(' in line and ')' in line and any(x in line for x in ['00:', '01:', '02:']):
            current_title = line.strip()
            
        # If not a URL or title, it's likely a description
        elif current_title and not current_description:
            current_description = line.strip()
    
    return video_highlights
def extract_video_urls(highlights_data):
    video_urls = []
    for highlight in highlights_data:
        if 'video_url' in highlight and highlight['video_url'].startswith('https://') and highlight['video_url'].endswith('.mp4'):
            video_urls.append(highlight['video_url'])
    return video_urls


def get_essential_game_info(game_pk):
    # Basic game info
    response = requests.get(f"{MLB_API_URL}?gamePk={game_pk}")
    game_info = response.json().get("dates", [])[0].get("games", [])[0]
    
    # Teams and Score
    teams_and_score = {
        'matchup': f"{game_info['teams']['away']['team']['name']} vs {game_info['teams']['home']['team']['name']}",
        'final_score': f"{game_info['teams']['away'].get('score', 0)} - {game_info['teams']['home'].get('score', 0)}",
        'venue': game_info.get('venue', {}).get('name', 'N/A'),
        'date': game_info['gameDate']
    }
    
    # Get inning breakdown and play descriptions
    game = statsapi.get('game', {'gamePk': game_pk})
    all_plays = game.get('liveData', {}).get('plays', {}).get('allPlays', [])
    
    inning_plays = []
    for play in all_plays:
        if play.get('about', {}).get('isComplete', False):
            inning_plays.append({
                'inning': f"{'Top' if play['about']['halfInning'] == 'top' else 'Bottom'} {play['about']['inning']}",
                'description': play['result'].get('description', ''),
                'score': f"{play['result'].get('awayScore', 0)}-{play['result'].get('homeScore', 0)}"
            })
    
    return {
        'game_info': teams_and_score,
        'plays': inning_plays
    }
def generate_full_baseball_commentary(game_data):
    # Parse scores and teams
    away_score, home_score = map(int, game_data['final_score'].split(' - '))
    teams = game_data['teams'].split(' vs ')
    winning_team = teams[0] if away_score > home_score else teams[1]
    
    commentary = []
    
    # Pre-game hype
    commentary.append(f"⚾ WELCOME TO {game_data['venue'].upper()}! ⚾")
    commentary.append(f"Today's matchup: {game_data['teams']} on {game_data['date']}")
    commentary.append("=" * 50)
    
    # Early innings
    current_inning = ""
    for play in game_data['plays']:
        if play['inning'] != current_inning:
            current_inning = play['inning']
            commentary.append(f"\n🎯 {current_inning.upper()}")
        
        # Add extra flair for scoring plays
        if any(score != '0' for score in play['score'].split('-')):
            commentary.append(f"💥 SCORING PLAY: {play['description']}")
            commentary.append(f"Score Update: {play['score']}")
        else:
            commentary.append(f"• {play['description']}")
    
    # Game wrap-up
    commentary.append("\n🏆 FINAL WRAP")
    commentary.append("=" * 50)
    commentary.append(f"{winning_team} takes this one!")
    commentary.append(f"Final Score: {game_data['final_score']}")
    
    # Game stats summary
    commentary.append("\n📊 GAME HIGHLIGHTS")
    commentary.append(f"Venue: {game_data['venue']}")
    commentary.append(f"Matchup: {game_data['teams']}")
    commentary.append(f"Date: {game_data['date']}")
    
    return commentary


# Get game data
game_pk = "748266"  # Your MLB game ID
game_details = get_essential_game_info(game_pk)

commentary = generate_full_baseball_commentary({
    'teams': game_details['game_info']['matchup'],
    'venue': game_details['game_info']['venue'],
    'date': game_details['game_info']['date'],
    'plays': game_details['plays'],
    'final_score': game_details['game_info']['final_score']
})

for line in commentary:
    print(line)
    time.sleep(0.5)  # Dramatic pacing

# Print with dramatic pauses
for line in commentary:
    print(line)
    time.sleep(1)

game_data = get_essential_game_info(game_pk)
geminicommentary = gemini_chat(f"Give a commentary on a match between  {game_data['game_info']['matchup']}  at {game_data['game_info']['venue']} on {game_data['game_info']['date']}  ")

# def display_game_details(game_pk):
#     game_data = get_essential_game_info(game_pk)
    
#     # Header - Teams and Venue
#     print("⚾ GAME DETAILS ⚾")
#     print("=" * 50)
#     print(f"MATCHUP: {game_data['game_info']['matchup']}")
#     print(f"VENUE: {game_data['game_info']['venue']}")
#     print(f"DATE: {game_data['game_info']['date']}")
#     print("=" * 50)
    
#     # Inning by Inning Breakdown
#     print("\n🎯 PLAY BY PLAY")
#     print("-" * 50)
#     current_inning = ""
#     for play in game_data['plays']:
#         if play['inning'] != current_inning:
#             current_inning = play['inning']
#             print(f"\n{current_inning.upper()}")
#         print(f"• {play['description']}")
#         print(f"  Score: {play['score']}")
    
#     # Final Score
#     print("\n🏆 FINAL SCORE")
#     print("-" * 50)
#     print(f"{game_data['game_info']['final_score']}")

# display_game_details(748266)