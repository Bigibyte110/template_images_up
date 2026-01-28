from flask import Flask, render_template, send_from_directory, request, send_file, session, jsonify, redirect, url_for
from werkzeug.utils import secure_filename
import os, uuid, time, json, re, asyncio
from io import BytesIO
import concurrent.futures
from datetime import datetime
from dotenv import load_dotenv
import base64
import hashlib
from struct import unpack

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Configure for Vercel - use environment variable for secret key
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24))
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Disable cache in development
if os.getenv('VERCEL_ENV') != 'production':
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# =============================================
# IN-MEMORY STORAGE FOR TEMPLATE GENERATION
# =============================================
TEMP_STORAGE = {}
PREVIEW_CACHE = {}

def cleanup_session_data(session_id):
    """Clean up temporary data for a session"""
    if session_id in TEMP_STORAGE:
        del TEMP_STORAGE[session_id]

# =============================================
# IMPROVED IMAGE GENERATOR WITH HTML2IMAGE
# =============================================

class ImageGenerator:
    """Image generator using html2image for HTML-to-image conversion"""
   
    @staticmethod
    def generate_template_image(template_num, data, edited_content, image_data, logo_data):
        """Generate a template image by rendering HTML to image"""
        try:
            from html2image import Html2Image
            from PIL import Image
            import tempfile
           
            # Prepare data with base64 images
            data_with_b64 = data.copy()
           
            # Convert image_data to base64
            if image_data:
                data_with_b64['image_b64'] = base64.b64encode(image_data).decode('utf-8')
            else:
                data_with_b64['image_b64'] = None
           
            # Convert logo_data to base64
            if logo_data:
                data_with_b64['logo_b64'] = base64.b64encode(logo_data).decode('utf-8')
            else:
                data_with_b64['logo_b64'] = None
           
            # Generate HTML content
            html_content = create_html_content(template_num, data_with_b64, edited_content)
           
            # Create temporary directory for output
            with tempfile.TemporaryDirectory() as temp_dir:
                # Initialize html2image
                hti = Html2Image(output_path=temp_dir, size=(1200, 800))
               
                # Generate image filename
                image_filename = f'template_{template_num}_{uuid.uuid4().hex[:8]}.jpg'
               
                # Screenshot the HTML
                hti.screenshot(
                    html_str=html_content,
                    save_as=image_filename,
                    size=(1200, 800)
                )
               
                # Read the generated image
                image_path = os.path.join(temp_dir, image_filename)
               
                if os.path.exists(image_path):
                    with open(image_path, 'rb') as f:
                        image_bytes = f.read()
                   
                    # Convert to JPEG with good quality
                    img = Image.open(BytesIO(image_bytes))
                    img_byte_arr = BytesIO()
                   
                    # Convert RGBA to RGB if necessary
                    if img.mode == 'RGBA':
                        img = img.convert('RGB')
                   
                    img.save(img_byte_arr, format='JPEG', quality=95, optimize=True)
                    return img_byte_arr.getvalue()
                else:
                    print(f"❌ Image file not created: {image_path}")
                    return ImageGenerator.generate_fallback_image(template_num, data_with_b64, edited_content, image_data, logo_data)
                   
        except Exception as e:
            print(f"HTML2Image generation error: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to PIL-based generation
            return ImageGenerator.generate_fallback_image(template_num, data, edited_content, image_data, logo_data)
   
    @staticmethod
    def generate_fallback_image(template_num, data, edited_content, image_data, logo_data):
        """Generate fallback image using PIL when html2image fails"""
        try:
            from PIL import Image, ImageDraw, ImageFont
            import textwrap
           
            # Create image
            img = Image.new('RGB', (1200, 800), color='white')
            d = ImageDraw.Draw(img)
           
            # Try to load fonts
            try:
                font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
                font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
                font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
            except:
                font_large = ImageFont.load_default()
                font_medium = ImageFont.load_default()
                font_small = ImageFont.load_default()
           
            # Use edited_content if available
            content = edited_content if edited_content else data
           
            # Add background color
            d.rectangle([(0, 0), (1200, 800)], fill=(240, 245, 250))
           
            # Add header
            d.rectangle([(0, 0), (1200, 150)], fill=(26, 43, 60))
           
            # Add title
            title = content.get('title', data.get('title', 'Team Event'))
            d.text((100, 60), f"Template #{template_num}", fill=(76, 182, 167), font=font_medium)
            d.text((100, 100), title[:30], fill='white', font=font_large)
           
            # Add company and date
            company = content.get('company', data.get('company', 'Your Company'))
            date_str = content.get('date', data.get('date', '2024'))
            d.text((1000, 100), company[:15], fill='white', font=font_small, anchor="ra")
            d.text((1000, 120), date_str[:10], fill=(200, 200, 200), font=font_small, anchor="ra")
           
            # Add main content area
            d.rectangle([(50, 180), (1150, 650)], fill='white', outline=(200, 200, 200), width=2)
           
            # Add user image if available
            if image_data:
                try:
                    user_img = Image.open(BytesIO(image_data))
                    # Resize to fit
                    user_img.thumbnail((500, 400), Image.Resampling.LANCZOS)
                    img.paste(user_img, (100, 220))
                    d.text((100, 630), "Your Image", fill=(100, 100, 100), font=font_small)
                except Exception as e:
                    print(f"Error pasting image: {e}")
                    d.rectangle([(100, 220), (600, 620)], fill=(230, 230, 230), outline=(200, 200, 200))
                    d.text((350, 420), "Image", fill=(150, 150, 150), font=font_large, anchor="mm")
           
            # Add text content
            y_position = 220
            content_lines = [
                f"Event: {title}",
                f"Company: {company}",
                f"Date: {date_str}",
                f"Author: {content.get('name', data.get('name', 'Team Member'))}",
            ]
           
            for line in content_lines:
                d.text((650, y_position), line, fill=(50, 50, 50), font=font_medium)
                y_position += 40
           
            # Add logo if available
            if logo_data:
                try:
                    logo_img = Image.open(BytesIO(logo_data))
                    logo_img.thumbnail((100, 100), Image.Resampling.LANCZOS)
                    # Create a white background for logo
                    logo_bg = Image.new('RGB', (120, 120), 'white')
                    logo_bg.paste(logo_img, (10, 10))
                    img.paste(logo_bg, (1050, 660))
                except Exception as e:
                    print(f"Error pasting logo: {e}")
           
            # Add footer
            d.rectangle([(0, 720), (1200, 800)], fill=(26, 43, 60))
            d.text((600, 760), "Generated with Smart Template Generator",
                  fill='white', font=font_small, anchor="mm")
           
            # Convert to bytes
            img_byte_arr = BytesIO()
            img.save(img_byte_arr, format='JPEG', quality=90, optimize=True)
            return img_byte_arr.getvalue()
           
        except Exception as e:
            print(f"Fallback image generation error: {e}")
            import traceback
            traceback.print_exc()
            return ImageGenerator.generate_simple_fallback(template_num, data)
   
    @staticmethod
    def generate_simple_fallback(template_num, data):
        """Generate very simple fallback when everything else fails"""
        from PIL import Image, ImageDraw, ImageFont
       
        img = Image.new('RGB', (1200, 800), color=(240, 245, 250))
        d = ImageDraw.Draw(img)
       
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        except:
            font = ImageFont.load_default()
       
        d.text((100, 100), f"Template #{template_num}", fill=(26, 43, 60), font=font)
        d.text((100, 150), data.get('title', 'Template')[:40], fill=(76, 182, 167), font=font)
        d.text((100, 200), data.get('company', '')[:40], fill=(100, 100, 100), font=font)
        d.text((100, 250), f"Date: {data.get('date', '2024')}", fill=(100, 100, 100), font=font)
       
        img_byte_arr = BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=85)
        return img_byte_arr.getvalue()

# =============================================
# SIMULATED AI (NO API KEY NEEDED)
# =============================================

class SimulatedAIAssistant:
    """Simulated AI for image analysis and text generation"""
   
    @staticmethod
    def analyze_image(image_bytes):
        """Analyze image without PIL"""
        try:
            width = height = 800  # Default fallback
           
            # Get image dimensions from bytes
            try:
                if image_bytes[:2] == b'\xff\xd8':  # JPEG
                    data = BytesIO(image_bytes)
                    data.seek(0)
                    while True:
                        marker = data.read(2)
                        if not marker or marker[0] != 0xFF:
                            break
                        marker_type = marker[1]
                        length = unpack('>H', data.read(2))[0]
                        if 0xC0 <= marker_type <= 0xC3:
                            data.read(1)
                            height = unpack('>H', data.read(2))[0]
                            width = unpack('>H', data.read(2))[0]
                            break
                        data.seek(length - 2, 1)
                elif image_bytes[:4] == b'\x89PNG':  # PNG
                    width = unpack('>I', image_bytes[16:20])[0]
                    height = unpack('>I', image_bytes[20:24])[0]
            except:
                pass
           
            # Basic analysis based on dimensions
            if width > height * 1.25:
                orientation = "horizontal"
                theme = "group or event photo"
            elif height > width * 1.25:
                orientation = "vertical"
                theme = "person or vertical photo"
            else:
                orientation = "square"
                theme = "balanced composition"
           
            colors_list = ["blue", "teal", "white"]
           
            return {
                "theme": f"{theme} ({orientation})",
                "mood": "professional",
                "colors": colors_list,
                "orientation": orientation,
                "title_ideas": [
                    "Team Gathering",
                    "Company Event",
                    "Professional Meeting",
                    "Success Celebration",
                    "Team Achievement",
                    "Corporate Event",
                    "Business Meeting",
                    "Annual Gathering"
                ],
                "description": f"A {orientation} photo capturing professional moments with the team.",
                "tags": ["team", "event", "professional", "business", "success", "corporate", "meeting", "celebration"]
            }
        except Exception as e:
            print(f"Image analysis error: {e}")
            return {
                "theme": "team event",
                "mood": "professional",
                "colors": ["blue", "teal", "white"],
                "orientation": "horizontal",
                "title_ideas": ["Team Event", "Company Gathering", "Success Celebration"],
                "description": "A professional team gathering.",
                "tags": ["team", "event", "professional"]
            }
   
    @staticmethod
    def generate_content_from_prompt(user_input, image_analysis=None):
        """Generate content suggestions without AI"""
        keywords = []
        for word in user_input.lower().split():
            clean_word = ''.join(c for c in word if c.isalnum())
            if len(clean_word) > 3 and clean_word not in ['company', 'event', 'date', 'name', 'with', 'team', 'our']:
                keywords.append(clean_word)
       
        if image_analysis:
            mood = image_analysis.get('mood', 'professional')
            theme = image_analysis.get('theme', 'team event')
        else:
            mood = 'professional'
            theme = 'team event'
       
        if mood == 'professional':
            title_base = ["Team", "Corporate", "Business", "Professional", "Annual"]
        elif mood == 'creative':
            title_base = ["Creative", "Innovative", "Dynamic", "Inspirational", "Visionary"]
        elif mood == 'joyful':
            title_base = ["Celebration", "Party", "Fun", "Happy", "Memorable"]
        else:
            title_base = ["Team", "Success", "Achievement", "Meeting", "Event"]
       
        titles = []
        for base in title_base[:3]:
            if keywords:
                titles.append(f"{base} {keywords[0].title()} Event")
            else:
                titles.append(f"{base} Gathering")
       
        titles.extend([
            "Together We Achieve More",
            "Building Success Together",
            "Our Winning Team"
        ])
       
        descriptions = [
            "Celebrating another successful milestone with our amazing team!",
            "Great times and greater achievements with the best team.",
            "Creating memories that last a lifetime.",
            f"Teamwork makes the dream work. Celebrating our {theme}!",
            f"Proud of what we achieve together as a {mood} team."
        ]
       
        hashtag_base = ["Team", "Success", "Business", "Corporate", "Event"]
        hashtags = [f"#{tag}" for tag in hashtag_base]
        if keywords:
            hashtags.extend([f"#{kw.title()}" for kw in keywords[:3]])
       
        ctas = [
            "Share your favorite moment!",
            "Tag your teammates!",
            "Like if you were there!",
            "Comment with your favorite memory!",
            "Share to spread the positivity!"
        ]
       
        return {
            "titles": titles[:5],
            "descriptions": descriptions[:3],
            "hashtags": hashtags[:8],
            "ctas": ctas[:3]
        }

AIAssistant = SimulatedAIAssistant

# =============================================
# IMPROVED SMART TEMPLATE ANALYZER
# =============================================

class SmartTemplateAnalyzer:
    """Enhanced analyzer that selects the best 4 templates from 20 available templates"""
   
    TEMPLATE_CHARACTERISTICS = {
        1: {
            "name": "Cyber-Creative", 
            "orientation": "any", 
            "style": "modern-tech", 
            "mood": "bold", 
            "best_for": ["tech", "creative", "startup", "innovation", "digital"],
            "keywords": ["cyber", "modern", "tech", "digital", "innovation", "creative", "bold", "edge"],
            "formality": "casual",
            "emphasis": "design",
            "color_scheme": "dark-vibrant"
        },
        2: {
            "name": "Brand Photo", 
            "orientation": "horizontal", 
            "style": "professional", 
            "mood": "clean", 
            "best_for": ["corporate", "team", "business", "office", "professional"],
            "keywords": ["brand", "corporate", "professional", "clean", "team", "business"],
            "formality": "formal",
            "emphasis": "people",
            "color_scheme": "light-professional"
        },
        3: {
            "name": "Editorial Creative", 
            "orientation": "vertical", 
            "style": "editorial", 
            "mood": "sophisticated", 
            "best_for": ["publishing", "magazine", "story", "editorial", "article"],
            "keywords": ["editorial", "magazine", "sophisticated", "story", "publishing"],
            "formality": "formal",
            "emphasis": "content",
            "color_scheme": "neutral-elegant"
        },
        4: {
            "name": "Dynamic Company", 
            "orientation": "square", 
            "style": "dynamic", 
            "mood": "energetic", 
            "best_for": ["company", "business", "modern", "growth", "success"],
            "keywords": ["dynamic", "energy", "modern", "company", "growth", "success"],
            "formality": "semi-formal",
            "emphasis": "brand",
            "color_scheme": "vibrant-professional"
        },
        5: {
            "name": "Tech Glitch-Art", 
            "orientation": "vertical", 
            "style": "tech", 
            "mood": "edgy", 
            "best_for": ["technology", "digital", "innovation", "gaming", "cyber"],
            "keywords": ["tech", "glitch", "digital", "edgy", "innovation", "gaming"],
            "formality": "casual",
            "emphasis": "design",
            "color_scheme": "dark-neon"
        },
        6: {
            "name": "Organic Tech", 
            "orientation": "square", 
            "style": "organic", 
            "mood": "natural", 
            "best_for": ["eco", "nature", "sustainable", "environment", "green"],
            "keywords": ["organic", "nature", "eco", "sustainable", "green", "environment"],
            "formality": "casual",
            "emphasis": "concept",
            "color_scheme": "earth-tones"
        },
        7: {
            "name": "Neo-Geometric", 
            "orientation": "any", 
            "style": "geometric", 
            "mood": "structured", 
            "best_for": ["design", "architecture", "creative", "modern", "art"],
            "keywords": ["geometric", "structure", "design", "architecture", "modern", "art"],
            "formality": "semi-formal",
            "emphasis": "design",
            "color_scheme": "bold-geometric"
        },
        8: {
            "name": "Perspective Grid", 
            "orientation": "horizontal", 
            "style": "3d", 
            "mood": "dimensional", 
            "best_for": ["innovation", "future", "design", "tech", "3d"],
            "keywords": ["perspective", "3d", "future", "innovation", "dimensional"],
            "formality": "casual",
            "emphasis": "design",
            "color_scheme": "dark-tech"
        },
        9: {
            "name": "Static Editorial", 
            "orientation": "vertical", 
            "style": "editorial", 
            "mood": "classic", 
            "best_for": ["formal", "news", "publishing", "corporate", "official"],
            "keywords": ["editorial", "formal", "classic", "news", "corporate"],
            "formality": "formal",
            "emphasis": "content",
            "color_scheme": "classic-professional"
        },
        10: {
            "name": "Modern Glass", 
            "orientation": "square", 
            "style": "glass", 
            "mood": "sleek", 
            "best_for": ["luxury", "premium", "modern", "elegant", "high-end"],
            "keywords": ["glass", "modern", "sleek", "luxury", "premium", "elegant"],
            "formality": "formal",
            "emphasis": "brand",
            "color_scheme": "minimal-luxury"
        },
        11: {
            "name": "Architectural", 
            "orientation": "vertical", 
            "style": "architectural", 
            "mood": "structural", 
            "best_for": ["architecture", "construction", "design", "building", "structure"],
            "keywords": ["architectural", "structure", "building", "design", "construction"],
            "formality": "formal",
            "emphasis": "design",
            "color_scheme": "dark-structured"
        },
        12: {
            "name": "Layered Monument", 
            "orientation": "horizontal", 
            "style": "monumental", 
            "mood": "grand", 
            "best_for": ["achievement", "milestone", "important", "celebration", "success"],
            "keywords": ["monument", "grand", "achievement", "milestone", "important"],
            "formality": "formal",
            "emphasis": "event",
            "color_scheme": "bold-impactful"
        },
        13: {
            "name": "Brand Team", 
            "orientation": "any", 
            "style": "team", 
            "mood": "unified", 
            "best_for": ["team", "company", "family", "group", "together"],
            "keywords": ["team", "unified", "together", "company", "family", "group"],
            "formality": "semi-formal",
            "emphasis": "people",
            "color_scheme": "warm-unified"
        },
        14: {
            "name": "Layered Monument Alt", 
            "orientation": "horizontal", 
            "style": "layered", 
            "mood": "epic", 
            "best_for": ["celebration", "event", "success", "party", "gathering"],
            "keywords": ["celebration", "epic", "event", "success", "party"],
            "formality": "semi-formal",
            "emphasis": "event",
            "color_scheme": "vibrant-celebratory"
        },
        15: {
            "name": "Dynamic Border", 
            "orientation": "square", 
            "style": "creative", 
            "mood": "artistic", 
            "best_for": ["art", "creative", "design", "artistic", "unique"],
            "keywords": ["dynamic", "artistic", "creative", "art", "design", "unique"],
            "formality": "casual",
            "emphasis": "design",
            "color_scheme": "bold-artistic"
        },
        16: {
            "name": "Tech Circuit", 
            "orientation": "vertical", 
            "style": "tech", 
            "mood": "futuristic", 
            "best_for": ["electronics", "engineering", "tech", "digital", "circuit"],
            "keywords": ["circuit", "tech", "electronics", "engineering", "futuristic"],
            "formality": "casual",
            "emphasis": "technology",
            "color_scheme": "dark-tech"
        },
        17: {
            "name": "Tech HUD", 
            "orientation": "any", 
            "style": "tech", 
            "mood": "futuristic", 
            "best_for": ["gaming", "tech", "interface", "digital", "hud"],
            "keywords": ["hud", "gaming", "tech", "interface", "futuristic", "digital"],
            "formality": "casual",
            "emphasis": "technology",
            "color_scheme": "dark-neon"
        },
        18: {
            "name": "Creative Brand", 
            "orientation": "any", 
            "style": "creative", 
            "mood": "artistic", 
            "best_for": ["art", "design", "creative", "brand", "unique"],
            "keywords": ["creative", "artistic", "brand", "art", "design", "unique"],
            "formality": "semi-formal",
            "emphasis": "brand",
            "color_scheme": "vibrant-creative"
        },
        19: {
            "name": "Wide Cinema", 
            "orientation": "horizontal", 
            "style": "cinematic", 
            "mood": "epic", 
            "best_for": ["film", "cinematic", "story", "movie", "narrative"],
            "keywords": ["cinema", "cinematic", "film", "story", "epic", "movie"],
            "formality": "semi-formal",
            "emphasis": "content",
            "color_scheme": "cinematic-wide"
        },
        20: {
            "name": "Editorial Brand", 
            "orientation": "any", 
            "style": "editorial", 
            "mood": "premium", 
            "best_for": ["branding", "luxury", "publishing", "premium", "elegant"],
            "keywords": ["editorial", "premium", "luxury", "brand", "elegant", "publishing"],
            "formality": "formal",
            "emphasis": "brand",
            "color_scheme": "elegant-premium"
        }
    }
   
    @staticmethod
    def analyze_input(data, image_orientation="horizontal", ai_image_analysis=None):
        """
        Enhanced analysis of user input with AI insights
        
        Args:
            data: Dictionary containing user form data (title, company, date, name)
            image_orientation: String indicating image orientation (horizontal, vertical, square)
            ai_image_analysis: Optional dictionary with AI analysis results
            
        Returns:
            Dictionary with comprehensive analysis including content_type, mood, formality, etc.
        """
        analysis = {
            "image_orientation": image_orientation,
            "content_type": "general",
            "mood": "professional",
            "industry": "general",
            "purpose": "team",
            "formality": "semi-formal",
            "emphasis": "people",
            "color_preference": "neutral",
            "keywords": []
        }
       
        # Combine all text for analysis
        all_text = f"{data.get('title', '')} {data.get('company', '')} {data.get('name', '')}".lower()
        
        # Extract keywords
        words = all_text.split()
        analysis["keywords"] = [w for w in words if len(w) > 3]
       
        # ENHANCED CONTENT TYPE DETECTION with priority scoring
        content_scores = {
            "tech": 0,
            "creative": 0,
            "business": 0,
            "event": 0,
            "team": 0,
            "nature": 0,
            "luxury": 0,
            "editorial": 0
        }
        
        # Tech indicators
        tech_words = ["tech", "software", "digital", "ai", "coding", "programming", "computer", 
                      "innovation", "startup", "app", "web", "cyber", "data", "cloud", "developer"]
        content_scores["tech"] = sum(3 if word in all_text else 0 for word in tech_words)
        
        # Creative indicators
        creative_words = ["creative", "design", "art", "studio", "agency", "graphic", "artist",
                         "visual", "brand", "aesthetic", "craft", "create", "designer"]
        content_scores["creative"] = sum(3 if word in all_text else 0 for word in creative_words)
        
        # Business indicators
        business_words = ["business", "corporate", "enterprise", "company", "office", "professional",
                         "meeting", "conference", "executive", "management", "leadership"]
        content_scores["business"] = sum(3 if word in all_text else 0 for word in business_words)
        
        # Event indicators
        event_words = ["event", "party", "celebration", "gathering", "festival", "ceremony",
                      "anniversary", "milestone", "launch", "opening", "night", "outing"]
        content_scores["event"] = sum(3 if word in all_text else 0 for word in event_words)
        
        # Team indicators
        team_words = ["team", "crew", "staff", "employee", "workforce", "department",
                     "together", "unity", "collaboration", "family", "group"]
        content_scores["team"] = sum(3 if word in all_text else 0 for word in team_words)
        
        # Nature indicators
        nature_words = ["nature", "eco", "environment", "sustainable", "green", "organic",
                       "natural", "earth", "planet", "clean"]
        content_scores["nature"] = sum(3 if word in all_text else 0 for word in nature_words)
        
        # Luxury indicators
        luxury_words = ["luxury", "premium", "elegant", "exclusive", "high-end", "prestige",
                       "elite", "sophisticated", "refined"]
        content_scores["luxury"] = sum(3 if word in all_text else 0 for word in luxury_words)
        
        # Editorial indicators
        editorial_words = ["editorial", "magazine", "publication", "article", "story",
                          "feature", "journal", "press"]
        content_scores["editorial"] = sum(3 if word in all_text else 0 for word in editorial_words)
        
        # Use AI image analysis to boost scores
        if ai_image_analysis:
            ai_theme = ai_image_analysis.get('theme', '').lower()
            ai_mood = ai_image_analysis.get('mood', '').lower()
            ai_tags = ai_image_analysis.get('tags', [])
            
            # Boost scores based on AI analysis
            if any(word in ai_theme for word in ['tech', 'digital', 'computer']):
                content_scores["tech"] += 5
            if any(word in ai_theme for word in ['creative', 'artistic', 'design']):
                content_scores["creative"] += 5
            if any(word in ai_theme for word in ['professional', 'business', 'corporate']):
                content_scores["business"] += 5
            if any(word in ai_theme for word in ['celebration', 'group', 'gathering']):
                content_scores["event"] += 5
            if 'team' in ai_tags or 'group' in ai_tags:
                content_scores["team"] += 5
        
        # Select content type with highest score
        max_score = max(content_scores.values())
        if max_score > 0:
            analysis["content_type"] = max(content_scores, key=content_scores.get)
        
        # MOOD DETECTION with context
        mood_scores = {
            "professional": 0,
            "creative": 0,
            "futuristic": 0,
            "joyful": 0,
            "elegant": 0,
            "bold": 0,
            "natural": 0
        }
        
        professional_words = ["professional", "business", "corporate", "formal", "official"]
        mood_scores["professional"] = sum(2 if word in all_text else 0 for word in professional_words)
        
        creative_words = ["creative", "artistic", "unique", "innovative", "original"]
        mood_scores["creative"] = sum(2 if word in all_text else 0 for word in creative_words)
        
        futuristic_words = ["future", "innovation", "tech", "digital", "modern", "next-gen"]
        mood_scores["futuristic"] = sum(2 if word in all_text else 0 for word in futuristic_words)
        
        joyful_words = ["celebration", "party", "fun", "happy", "joy", "festive", "exciting"]
        mood_scores["joyful"] = sum(2 if word in all_text else 0 for word in joyful_words)
        
        elegant_words = ["elegant", "luxury", "premium", "sophisticated", "refined"]
        mood_scores["elegant"] = sum(2 if word in all_text else 0 for word in elegant_words)
        
        bold_words = ["bold", "dynamic", "powerful", "strong", "impactful"]
        mood_scores["bold"] = sum(2 if word in all_text else 0 for word in bold_words)
        
        natural_words = ["natural", "organic", "eco", "green", "sustainable"]
        mood_scores["natural"] = sum(2 if word in all_text else 0 for word in natural_words)
        
        # Use AI mood if available
        if ai_image_analysis:
            ai_mood = ai_image_analysis.get('mood', '').lower()
            if ai_mood in mood_scores:
                mood_scores[ai_mood] += 3
        
        max_mood_score = max(mood_scores.values())
        if max_mood_score > 0:
            analysis["mood"] = max(mood_scores, key=mood_scores.get)
        
        # FORMALITY LEVEL
        formal_indicators = ["corporate", "business", "professional", "official", "formal", "executive"]
        casual_indicators = ["party", "fun", "casual", "relaxed", "friendly", "team", "night"]
        
        formal_count = sum(1 for word in formal_indicators if word in all_text)
        casual_count = sum(1 for word in casual_indicators if word in all_text)
        
        if formal_count > casual_count + 1:
            analysis["formality"] = "formal"
        elif casual_count > formal_count + 1:
            analysis["formality"] = "casual"
        else:
            analysis["formality"] = "semi-formal"
        
        # EMPHASIS DETECTION
        if any(word in all_text for word in ["team", "people", "staff", "crew", "group"]):
            analysis["emphasis"] = "people"
        elif any(word in all_text for word in ["brand", "logo", "company", "business"]):
            analysis["emphasis"] = "brand"
        elif any(word in all_text for word in ["event", "celebration", "party", "gathering"]):
            analysis["emphasis"] = "event"
        elif any(word in all_text for word in ["design", "creative", "art", "visual"]):
            analysis["emphasis"] = "design"
        
        # DATE-BASED CONTEXT
        date_str = data.get('date', '')
        if '12' in date_str or 'christmas' in all_text or 'holiday' in all_text:
            analysis["mood"] = "joyful"
            mood_scores["joyful"] += 3
        
        return analysis
   
    @staticmethod
    def select_best_templates(user_analysis, ai_image_analysis=None):
        """
        Enhanced template selection with multi-factor scoring
        
        Args:
            user_analysis: Dictionary from analyze_input()
            ai_image_analysis: Optional AI analysis results
            
        Returns:
            List of 4 best template numbers
        """
        scores = {}
        
        print(f"\n🔍 User Analysis: {user_analysis}")
        if ai_image_analysis:
            print(f"🎨 AI Image Analysis: {ai_image_analysis.get('theme', 'N/A')}, {ai_image_analysis.get('mood', 'N/A')}")
       
        for template_num, template_info in SmartTemplateAnalyzer.TEMPLATE_CHARACTERISTICS.items():
            score = 0
            score_breakdown = {}
            
            # 1. ORIENTATION MATCH (25 points)
            if template_info["orientation"] == user_analysis["image_orientation"]:
                score += 25
                score_breakdown["orientation"] = 25
            elif template_info["orientation"] == "any":
                score += 20
                score_breakdown["orientation"] = 20
            else:
                # Penalty for wrong orientation
                score -= 5
                score_breakdown["orientation"] = -5
            
            # 2. CONTENT TYPE MATCH (30 points)
            content_match_score = 0
            for best_for in template_info["best_for"]:
                if best_for in user_analysis["content_type"]:
                    content_match_score += 15
                elif any(best_for in keyword for keyword in user_analysis.get("keywords", [])):
                    content_match_score += 10
            
            # Bonus for exact style match
            if template_info["style"] in user_analysis["content_type"]:
                content_match_score += 10
            
            score += min(content_match_score, 30)  # Cap at 30
            score_breakdown["content"] = min(content_match_score, 30)
            
            # 3. MOOD MATCH (20 points)
            mood_groups = {
                "professional": ["clean", "sophisticated", "classic", "premium", "professional", "structured", "sleek"],
                "creative": ["bold", "artistic", "dimensional", "structured", "creative", "edgy", "unique"],
                "futuristic": ["edgy", "futuristic", "modern-tech", "tech", "dimensional", "sleek"],
                "joyful": ["energetic", "artistic", "bold", "dynamic", "epic"],
                "elegant": ["sophisticated", "classic", "premium", "sleek", "refined"],
                "bold": ["bold", "edgy", "dynamic", "energetic", "grand", "epic"],
                "natural": ["natural", "organic", "clean", "simple"]
            }
            
            mood_score = 0
            user_mood = user_analysis.get("mood", "professional")
            if user_mood in mood_groups:
                if template_info["mood"] in mood_groups[user_mood]:
                    mood_score = 20
                elif any(mood in mood_groups[user_mood] for mood in [template_info["mood"]]):
                    mood_score = 10
            
            score += mood_score
            score_breakdown["mood"] = mood_score
            
            # 4. FORMALITY MATCH (15 points)
            formality_score = 0
            if template_info.get("formality") == user_analysis.get("formality"):
                formality_score = 15
            elif (template_info.get("formality") == "semi-formal" or 
                  user_analysis.get("formality") == "semi-formal"):
                formality_score = 10
            
            score += formality_score
            score_breakdown["formality"] = formality_score
            
            # 5. EMPHASIS MATCH (10 points)
            if template_info.get("emphasis") == user_analysis.get("emphasis"):
                score += 10
                score_breakdown["emphasis"] = 10
            else:
                score_breakdown["emphasis"] = 0
            
            # 6. KEYWORD MATCHING (15 points)
            keyword_score = 0
            user_keywords = user_analysis.get("keywords", [])
            template_keywords = template_info.get("keywords", [])
            
            for user_kw in user_keywords:
                for template_kw in template_keywords:
                    if user_kw in template_kw or template_kw in user_kw:
                        keyword_score += 2
            
            score += min(keyword_score, 15)  # Cap at 15
            score_breakdown["keywords"] = min(keyword_score, 15)
            
            # 7. AI IMAGE ANALYSIS BONUS (10 points)
            ai_bonus = 0
            if ai_image_analysis:
                ai_theme = ai_image_analysis.get('theme', '').lower()
                ai_tags = ai_image_analysis.get('tags', [])
                
                # Check if AI analysis matches template characteristics
                for tag in ai_tags:
                    if tag.lower() in template_info.get("keywords", []):
                        ai_bonus += 2
                
                if any(word in ai_theme for word in template_info.get("keywords", [])):
                    ai_bonus += 5
            
            score += min(ai_bonus, 10)
            score_breakdown["ai_analysis"] = min(ai_bonus, 10)
            
            scores[template_num] = {
                "total": score,
                "breakdown": score_breakdown
            }
            
            print(f"Template {template_num} ({template_info['name']}): {score} points - {score_breakdown}")
       
        # Sort by score
        sorted_templates = sorted(scores.items(), key=lambda x: x[1]["total"], reverse=True)
        
        # Select top templates with diversity
        best_templates = []
        used_styles = set()
        used_moods = set()
        
        # First pass: Get highest scoring template
        if sorted_templates:
            best_template = sorted_templates[0][0]
            best_templates.append(best_template)
            template_info = SmartTemplateAnalyzer.TEMPLATE_CHARACTERISTICS[best_template]
            used_styles.add(template_info["style"])
            used_moods.add(template_info["mood"])
        
        # Second pass: Add templates with diversity
        for template_num, score_info in sorted_templates[1:]:
            if len(best_templates) >= 4:
                break
            
            template_info = SmartTemplateAnalyzer.TEMPLATE_CHARACTERISTICS[template_num]
            
            # Prefer templates with different styles/moods for variety
            diversity_score = 0
            if template_info["style"] not in used_styles:
                diversity_score += 5
            if template_info["mood"] not in used_moods:
                diversity_score += 5
            
            # If we have less than 4 and this has decent score, add it
            if score_info["total"] > 20 or len(best_templates) < 3:
                best_templates.append(template_num)
                used_styles.add(template_info["style"])
                used_moods.add(template_info["mood"])
        
        # Ensure we have exactly 4 templates
        if len(best_templates) < 4:
            for template_num, _ in sorted_templates:
                if template_num not in best_templates:
                    best_templates.append(template_num)
                if len(best_templates) >= 4:
                    break
        
        print(f"\n✅ Selected Templates: {best_templates}")
        for template_num in best_templates:
            info = SmartTemplateAnalyzer.TEMPLATE_CHARACTERISTICS[template_num]
            print(f"  - Template {template_num}: {info['name']} (Score: {scores[template_num]['total']})")
       
        return best_templates[:4]

# =============================================
# TEXT CONTENT MANAGER
# =============================================

class TextContentManager:
    """Manage editable text content for templates in memory"""
   
    TEXT_STORAGE = {}
   
    @staticmethod
    def save_text_content(session_id, template_num, content_data):
        if session_id not in TextContentManager.TEXT_STORAGE:
            TextContentManager.TEXT_STORAGE[session_id] = {}
       
        TextContentManager.TEXT_STORAGE[session_id][template_num] = content_data
        return True
   
    @staticmethod
    def load_text_content(session_id, template_num):
        if (session_id in TextContentManager.TEXT_STORAGE and
            template_num in TextContentManager.TEXT_STORAGE[session_id]):
            return TextContentManager.TEXT_STORAGE[session_id][template_num]
        return None
   
    @staticmethod
    def delete_text_content(session_id):
        if session_id in TextContentManager.TEXT_STORAGE:
            del TextContentManager.TEXT_STORAGE[session_id]

# =============================================
# HTML TEMPLATE FUNCTION
# =============================================

def create_html_content(template_num, data, editable_texts=None):
    """Create HTML content with embedded base64 images - PLACEHOLDER
    
    NOTE: This is a placeholder. You should paste your complete 
    create_html_content function with all 20 templates here.
    """
   
    # Use editable texts if provided, otherwise use original data
    if editable_texts:
        content = {
            "title": editable_texts.get('title', data.get('title', 'TEAM NIGHT OUT')),
            "company": editable_texts.get('company', data.get('company', 'NUB')),
            "date": editable_texts.get('date', data.get('date', '2024-01-01')),
            "name": editable_texts.get('name', data.get('name', 'Author Name')),
            "custom_text1": editable_texts.get('custom_text1', ''),
            "custom_text2": editable_texts.get('custom_text2', ''),
            "hashtags": editable_texts.get('hashtags', ''),
            "cta": editable_texts.get('cta', '')
        }
    else:
        content = {
            "title": data.get('title', 'TEAM NIGHT OUT'),
            "company": data.get('company', 'NUB'),
            "date": data.get('date', '2024-01-01'),
            "name": data.get('name', 'Author Name'),
            "custom_text1": data.get('custom_text1', ''),
            "custom_text2": data.get('custom_text2', ''),
            "hashtags": data.get('hashtags', ''),
            "cta": data.get('cta', '')
        }
   
    # Get base64 images from data
    if data.get("image_b64"):
        image_url = f"data:image/jpeg;base64,{data['image_b64']}"
    else:
        image_url = "https://via.placeholder.com/800x600/1A2B3C/FFFFFF?text=No+Image"
   
    if data.get("logo_b64"):
        logo_url = f"data:image/jpeg;base64,{data['logo_b64']}"
    else:
        logo_url = "https://via.placeholder.com/200x200/4CB6A7/FFFFFF?text=LOGO"
    
    # NOTE: Include all your 20 template HTML code here
    # For now, using a simple template as placeholder
    if template_num == 1:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cyber-Creative Brand Frame</title>
    <style>
        :root {{ --brand-teal: #4CB6A7; --brand-navy: #1A2B3C; --brand-white: #FFFFFF; }}
        body {{ display: flex; justify-content: center; align-items: center; min-height: 100vh; background-color: #0d151d; margin: 0; font-family: 'Inter', sans-serif; }}
        .creative-canvas {{ position: relative; width: 1000px; height: 600px; background-color: var(--brand-navy); overflow: hidden; display: flex; box-shadow: 0 50px 100px rgba(0,0,0,0.5); }}
        .creative-canvas::before {{ content: ""; position: absolute; top: 0; left: -10%; width: 50%; height: 100%; background-color: var(--brand-teal); transform: skewX(-15deg); z-index: 1; }}
        .image-side {{ position: relative; width: 65%; height: 100%; z-index: 2; clip-path: polygon(0 0, 100% 0, 85% 100%, 0% 100%); overflow: hidden; }}
        .image-side img {{ width: 100%; height: 100%; object-fit: cover; filter: saturate(1.2) contrast(1.1); }}
        .content-side {{ position: relative; width: 35%; padding: 40px; display: flex; flex-direction: column; justify-content: center; align-items: flex-start; z-index: 3; color: var(--brand-white); }}
        .logo-ring {{ position: absolute; top: 40px; right: 40px; width: 120px; height: 120px; background: var(--brand-white); border-radius: 50%; display: flex; align-items: center; justify-content: center; padding: 15px; box-shadow: 0 0 30px var(--brand-teal); z-index: 10; }}
        .logo-ring img {{ width: 100%; height: auto; }}
        .content-side h1 {{ font-size: 64px; line-height: 0.9; margin: 0; font-weight: 900; text-transform: uppercase; letter-spacing: -2px; }}
        .content-side h1 span {{ color: var(--brand-teal); display: block; }}
        .tagline {{ margin-top: 20px; font-size: 14px; text-transform: uppercase; letter-spacing: 5px; border-left: 3px solid var(--brand-teal); padding-left: 15px; opacity: 0.8; }}
        .floating-lines {{ position: absolute; bottom: -20px; left: 20%; font-size: 120px; color: var(--brand-white); opacity: 0.05; font-weight: 900; z-index: 1; pointer-events: none; }}
    </style>
</head>
<body>
    <div class="creative-canvas">
        <div class="floating-lines">CREATIVE</div>
        <div class="image-side">
            <img src="{image_url}" alt="Main Image">
        </div>
        <div class="logo-ring">
            <img src="{logo_url}" alt="Brand Logo">
        </div>
        <div class="content-side">
            <h1>{content['title']}<br><span>{content['company']}</span></h1>
            <div class="tagline">{content['date']} | {content['name']}</div>
        </div>
    </div>
</body>
</html>"""
    
    # Continue with other templates (2-20) - same as before...
    # For brevity, I'll include the rest of the templates here...
    
    # Template 2
    elif template_num == 2:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Brand Photo Frame</title>
    <style>
        :root {{ --brand-teal: #4CB6A7; --brand-navy: #1A2B3C; --brand-white: #FFFFFF; }}
        body {{ display: flex; justify-content: center; align-items: center; min-height: 100vh; background-color: #d8dee9; margin: 0; font-family: 'Segoe UI', Roboto, sans-serif; }}
        .outer-frame {{ position: relative; background-color: var(--brand-white); padding: 25px; border-bottom: 20px solid var(--brand-navy); box-shadow: 0 40px 80px rgba(0,0,0,0.15); max-width: 900px; display: flex; flex-direction: column; }}
        .outer-frame::before {{ content: ""; position: absolute; top: 0; left: 0; width: 120px; height: 120px; background: linear-gradient(135deg, var(--brand-teal) 0%, var(--brand-teal) 50%, transparent 50%); z-index: 5; }}
        .photo-container {{ position: relative; width: 100%; line-height: 0; }}
        .photo-container img {{ width: 100%; height: auto; display: block; border-radius: 4px; }}
        .glass-overlay {{ position: absolute; bottom: 30px; left: 30px; right: 30px; background: rgba(26, 43, 60, 0.85); backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.1); padding: 20px 40px; display: flex; justify-content: space-between; align-items: center; border-radius: 12px; z-index: 10; }}
        .brand-left {{ display: flex; align-items: center; gap: 20px; }}
        .brand-left img {{ height: 55px; width: auto; filter: drop-shadow(0 0 8px rgba(255,255,255,0.2)); }}
        .brand-text h1 {{ color: white; margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 0.5px; }}
        .brand-text p {{ color: var(--brand-teal); margin: 2px 0 0; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 2px; }}
        .deco-dots {{ position: absolute; top: 40px; right: 40px; display: grid; grid-template-columns: repeat(4, 8px); gap: 8px; z-index: 10; }}
        .dot {{ width: 8px; height: 8px; background-color: var(--brand-teal); border-radius: 50%; opacity: 0.6; }}
    </style>
</head>
<body>
    <div class="outer-frame">
        <div class="deco-dots">
            <div class="dot"></div><div class="dot"></div><div class="dot"></div><div class="dot"></div>
            <div class="dot"></div><div class="dot"></div><div class="dot"></div><div class="dot"></div>
        </div>
        <div class="photo-container">
            <img src="{image_url}" alt="Team Photo">
            <div class="glass-overlay">
                <div class="brand-left">
                    <img src="{logo_url}" alt="Logo">
                    <div class="brand-text">
                        <h1>{content['title']}</h1>
                        <p>{content['company']} • {content['date']}</p>
                    </div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>"""
    
    # Continue with templates 3-20...
    # For the complete code, you should include all your template HTML functions here
    elif template_num == 3:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Editorial Creative Brand Frame</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-height: 100vh; background-color: #0b1219; display: flex; justify-content: center; align-items: center; font-family: Arial, sans-serif; }}
.wrapper {{ width: 100%; max-width: 900px; padding: 30px; position: relative; }}
.wrapper::before {{ content: ""; position: absolute; width: 70%; height: 60%; top: 20%; left: 15%; background-color: rgba(76, 182, 167, 0.22); filter: blur(80px); z-index: -1; }}
.frame {{ background-color: rgb(26, 43, 60); padding: 18px; border-radius: 26px; position: relative; transform: translate(12px, -12px); box-shadow: 0 45px 90px rgba(0, 0, 0, 0.6); }}
.canvas {{ background-color: #ffffff; border-radius: 18px; padding: 16px; display: grid; grid-template-columns: 56px 1fr; gap: 14px; }}
.logo-strip {{ background-color: rgba(26, 43, 60, 0.06); border-radius: 12px; display: flex; align-items: center; justify-content: center; }}
.logo-strip img {{ width: 34px; transform: rotate(-90deg); }}
.image-box {{ border-radius: 14px; overflow: hidden; }}
.image-box img {{ width: 100%; height: auto; display: block; }}
.caption {{ grid-column: 2; margin-top: 10px; padding: 10px 14px; border-left: 3px solid rgb(76, 182, 167); color: rgb(26, 43, 60); font-size: 14px; }}
@media (max-width: 600px) {{ .canvas {{ grid-template-columns: 1fr; }} .logo-strip {{ height: 44px; }} .logo-strip img {{ transform: rotate(0deg); }} .caption {{ grid-column: 1; }} }}
</style>
</head>
<body>
<div class="wrapper">
    <div class="frame">
        <div class="canvas">
            <div class="logo-strip">
                <img src="{logo_url}" alt="Brand Logo">
            </div>
            <div class="image-box">
                <img src="{image_url}" alt="Main Image">
            </div>
            <div class="caption">
                {data.get('company', 'NUB')} | {data.get('title', 'Team Event')} | {data.get('date', '2024')}
            </div>
        </div>
    </div>
</div>
</body>
</html>"""
    
    # Template 4 HTML (original)
    elif template_num == 4:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Dynamic Company Brand Frame</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;700;900&display=swap');
        :root {{ --brand-teal: #4CB6A7; --brand-navy: #1A2B3C; --brand-white: #FFFFFF; --brand-light-teal: rgba(76, 182, 167, 0.15); }}
        body {{ margin: 0; padding: 0; display: flex; justify-content: center; align-items: center; min-height: 100vh; background-color: #f0f4f8; font-family: 'Outfit', sans-serif; overflow: hidden; }}
        .bg-shapes {{ position: absolute; width: 100%; height: 100%; overflow: hidden; z-index: -1; }}
        .shape {{ position: absolute; filter: blur(40px); opacity: 0.4; animation: move 20s infinite alternate ease-in-out; }}
        .shape-1 {{ width: 400px; height: 400px; background: var(--brand-teal); top: -100px; left: -100px; border-radius: 40% 60% 70% 30% / 40% 50% 60% 70%; }}
        .shape-2 {{ width: 500px; height: 500px; background: var(--brand-navy); bottom: -150px; right: -150px; border-radius: 70% 30% 30% 70% / 70% 30% 70% 30%; animation-delay: -5s; }}
        @keyframes move {{ from {{ transform: translate(0, 0) rotate(0deg); }} to {{ transform: translate(100px, 50px) rotate(15deg); }} }}
        .brand-canvas {{ position: relative; width: 90%; max-width: 1000px; background: var(--brand-white); padding: 40px; border-radius: 30px; box-shadow: 0 40px 100px rgba(26, 43, 60, 0.15); display: flex; flex-direction: column; gap: 30px; }}
        .logo-section {{ display: flex; justify-content: space-between; align-items: center; }}
        .logo-section img {{ height: 60px; width: auto; }}
        .brand-badge {{ background: var(--brand-light-teal); color: var(--brand-teal); padding: 8px 20px; border-radius: 50px; font-weight: 700; font-size: 14px; letter-spacing: 1px; text-transform: uppercase; }}
        .image-wrapper {{ position: relative; width: 100%; background: var(--brand-navy); border-radius: 20px; overflow: hidden; padding: 15px; box-sizing: border-box; transition: transform 0.4s ease; }}
        .image-wrapper:hover {{ transform: translateY(-5px); }}
        .image-wrapper img {{ width: 100%; height: auto; display: block; border-radius: 12px; object-fit: contain; }}
        .frame-footer {{ display: grid; grid-template-columns: 1fr auto; align-items: end; }}
        .title-block h1 {{ margin: 0; color: var(--brand-navy); font-size: 48px; font-weight: 900; line-height: 1; letter-spacing: -1px; }}
        .title-block p {{ margin: 10px 0 0; color: #64748b; font-size: 18px; font-weight: 400; }}
        .accent-bar {{ width: 60px; height: 8px; background: var(--brand-teal); border-radius: 10px; margin-bottom: 15px; }}
        .logo-shape-deco {{ position: absolute; bottom: -20px; right: 40px; width: 100px; height: 50px; background: var(--brand-navy); border-radius: 0 0 100px 100px; z-index: -1; }}
    </style>
</head>
<body>
    <div class="bg-shapes">
        <div class="shape shape-1"></div>
        <div class="shape shape-2"></div>
    </div>
    <div class="brand-canvas">
        <div class="logo-section">
            <img src="{logo_url}" alt="Company Logo">
            <div class="brand-badge">{data.get('company', 'NUB')}</div>
        </div>
        <div class="image-wrapper">
            <img src="{image_url}" alt="Team Night Out">
        </div>
        <div class="frame-footer">
            <div class="title-block">
                <div class="accent-bar"></div>
                <h1>{data.get('title', 'OUR TEAM NIGHT OUT')}</h1>
                <p>{data.get('name', 'Author Name')} • {data.get('date', '2024')}</p>
            </div>
            <div style="text-align: right; color: var(--brand-teal); font-weight: 900; font-size: 24px;">
                {data.get('date', '2024').split('-')[0] if '-' in data.get('date', '2024') else data.get('date', '2024')}
            </div>
        </div>
        <div class="logo-shape-deco"></div>
    </div>
</body>
</html>"""
    
    # Template 5 HTML (Tech Glitch-Art Frame)
    elif template_num == 5:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tech Glitch-Art Frame</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@900&family=Work+Sans:wght@300;800&family=JetBrains+Mono:wght@400;700&display=swap');

        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #0A1622;
            --brand-white: #FFFFFF;
            --brand-bg: #050a0f;
            --glitch-red: #ff0055;
        }}

        body {{
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: var(--brand-bg);
            font-family: 'Work Sans', sans-serif;
            overflow: hidden;
        }}

        /* Large Format Canvas */
        .canvas-container {{
            position: relative;
            width: 1150px;
            height: 750px;
            background: var(--brand-navy);
            box-shadow: 0 0 100px rgba(0,0,0,0.8);
            overflow: hidden;
        }}

        /* Glitch Stripe Background */
        .glitch-stripe {{
            position: absolute;
            height: 2px;
            background: var(--brand-teal);
            opacity: 0.3;
            z-index: 1;
        }}

        /* Main Image Container: Fragmented Frame */
        .photo-fragment-container {{
            position: absolute;
            top: 60px;
            left: 60px;
            right: 60px;
            bottom: 60px;
            z-index: 10;
        }}

        .photo-offset-bg {{
            position: absolute;
            top: 15px;
            left: 15px;
            width: 100%;
            height: 100%;
            border: 2px solid var(--glitch-red);
            opacity: 0.5;
            z-index: 5;
        }}

        .main-photo-wrap {{
            position: relative;
            width: 100%;
            height: 100%;
            background: var(--brand-white);
            padding: 3px;
            z-index: 15;
            box-shadow: 0 30px 60px rgba(0,0,0,0.5);
        }}

        .main-photo-wrap img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
            filter: grayscale(0.2) contrast(1.1);
        }}

        /* Glitch Block Overlays */
        .glitch-block {{
            position: absolute;
            background: var(--brand-teal);
            z-index: 20;
            mix-blend-mode: screen;
        }}

        /* Branding: Deconstructed */
        .brand-header {{
            position: absolute;
            top: 20px;
            left: 80px;
            z-index: 30;
            display: flex;
            align-items: center;
            gap: 20px;
        }}

        .logo-static {{
            background: var(--brand-white);
            padding: 15px 25px;
            box-shadow: 8px 8px 0 var(--brand-teal);
        }}

        .logo-static img {{
            height: 40px;
            width: auto;
        }}

        /* Hero Typography: Layered & Distorted */
        .glitch-text-wrap {{
            position: absolute;
            bottom: 40px;
            right: 40px;
            z-index: 40;
            text-align: right;
        }}

        .glitch-text-wrap h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 120px;
            line-height: 0.75;
            margin: 0;
            color: var(--brand-white);
            text-transform: uppercase;
            letter-spacing: -6px;
            position: relative;
        }}

        .glitch-text-wrap h1 span {{
            display: block;
            color: var(--brand-teal);
            text-shadow: 4px 0 var(--glitch-red);
        }}

        .event-tag {{
            background: var(--brand-white);
            color: var(--brand-navy);
            display: inline-block;
            padding: 8px 20px;
            font-weight: 900;
            font-size: 14px;
            letter-spacing: 4px;
            margin-top: 15px;
            text-transform: uppercase;
        }}

        /* Structural Decors */
        .frame-bit {{
            position: absolute;
            width: 200px;
            height: 4px;
            background: var(--brand-white);
            z-index: 25;
            opacity: 0.8;
        }}
    </style>
</head>
<body>
    <div class="canvas-container">
        <!-- Background Noise/Lines -->
        <div class="glitch-stripe" style="top: 15%; width: 100%;"></div>
        <div class="glitch-stripe" style="top: 45%; width: 60%; left: 20%;"></div>
        <div class="glitch-stripe" style="bottom: 20%; width: 100%;"></div>

        <!-- Branding Section -->
        <div class="brand-header">
            <div class="logo-static">
                <img src="{logo_url}" alt="Logo">
            </div>
        </div>

        <!-- The Photo Area -->
        <div class="photo-fragment-container">
            <!-- Shadow/Offset frame -->
            <div class="photo-offset-bg"></div>
            
            <!-- Deconstructed Bits -->
            <div class="frame-bit" style="top: -2px; left: 100px;"></div>
            <div class="frame-bit" style="bottom: -2px; right: 200px; width: 300px; background: var(--brand-teal);"></div>

            <div class="main-photo-wrap">
                <img src="{image_url}" alt="Team Night Out">
            </div>

            <!-- Glitch Overlays -->
            <div class="glitch-block" style="top: 20%; left: -10px; width: 40px; height: 100px;"></div>
            <div class="glitch-block" style="bottom: 10%; right: -20px; width: 15px; height: 150px; background: var(--glitch-red);"></div>
        </div>

        <!-- Typography -->
        <div class="glitch-text-wrap">
            <h1>{data.get('title', 'TEAM').split()[0] if data.get('title') else 'TEAM'}<span>{data.get('title', 'NIGHT').split()[-1] if data.get('title') else 'NIGHT'}</span></h1>
            <div class="event-tag">{data.get('company', 'UNITED_DISRUPTION')}</div>
        </div>
    </div>
</body>
</html>"""
    
    # Template 6 HTML (Organic Tech Brand Experience)
    elif template_num == 6:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Organic Tech Brand Experience</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;600;900&family=Playfair+Display:ital,wght@1,900&display=swap');

        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #1A2B3C;
            --brand-white: #FFFFFF;
            --brand-bg: #fdfdfd;
        }}

        body {{
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: var(--brand-bg);
            font-family: 'Outfit', sans-serif;
            overflow: hidden;
        }}

        /* Fluid Background Decor */
        .fluid-bg {{
            position: absolute;
            width: 100%;
            height: 100%;
            z-index: 0;
        }}

        .blob {{
            position: absolute;
            background: var(--brand-teal);
            filter: blur(80px);
            opacity: 0.15;
            border-radius: 50%;
        }}

        /* Main Editorial Canvas */
        .editorial-canvas {{
            position: relative;
            width: 90vw;
            max-width: 1200px;
            height: 800px;
            z-index: 10;
            display: grid;
            grid-template-columns: 1fr 1.2fr;
            align-items: center;
        }}

        /* Left Side: Branding & Text */
        .brand-content {{
            padding-right: 40px;
            z-index: 20;
        }}

        .logo-section {{
            margin-bottom: 60px;
        }}

        .logo-section img {{
            height: 80px;
            width: auto;
        }}

        .hero-title {{
            position: relative;
        }}

        .hero-title h1 {{
            font-size: clamp(60px, 8vw, 110px);
            font-weight: 900;
            color: var(--brand-navy);
            margin: 0;
            line-height: 0.85;
            letter-spacing: -4px;
        }}

        .hero-title h1 span {{
            display: block;
            font-family: 'Playfair Display', serif;
            font-style: italic;
            color: var(--brand-teal);
            padding-left: 20px;
        }}

        .description {{
            margin-top: 30px;
            font-size: 18px;
            color: #64748b;
            max-width: 320px;
            line-height: 1.6;
            border-left: 4px solid var(--brand-teal);
            padding-left: 20px;
        }}

        /* Right Side: Photo with Soft Glass Effect */
        .photo-side {{
            position: relative;
            height: 90%;
            display: flex;
            align-items: center;
            justify-content: center;
        }}

        .photo-holder {{
            position: relative;
            width: 100%;
            height: 100%;
            background: var(--brand-white);
            padding: 20px;
            border-radius: 40px;
            box-shadow: 0 50px 100px rgba(26, 43, 60, 0.08);
            transform: rotate(2deg);
            transition: transform 0.6s cubic-bezier(0.23, 1, 0.32, 1);
        }}

        .photo-holder:hover {{
            transform: rotate(0deg) scale(1.02);
        }}

        .photo-inner {{
            width: 100%;
            height: 100%;
            overflow: hidden;
            border-radius: 25px;
            background: var(--brand-navy);
        }}

        .photo-inner img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
        }}

        /* Floating Meta Tags */
        .tag-container {{
            position: absolute;
            bottom: -30px;
            right: 40px;
            display: flex;
            gap: 15px;
        }}

        .pill-tag {{
            background: var(--brand-navy);
            color: var(--brand-white);
            padding: 12px 25px;
            border-radius: 50px;
            font-weight: 600;
            font-size: 14px;
            box-shadow: 0 15px 30px rgba(26, 43, 60, 0.2);
        }}

        .teal-pill {{
            background: var(--brand-teal);
            color: var(--brand-navy);
        }}

        /* Corner Decorative Lines */
        .corner-deco {{
            position: absolute;
            top: 20px;
            right: 20px;
            width: 150px;
            height: 150px;
            border-top: 2px solid rgba(76, 182, 167, 0.3);
            border-right: 2px solid rgba(76, 182, 167, 0.3);
            border-radius: 0 40px 0 0;
        }}
    </style>
</head>
<body>
    <div class="fluid-bg">
        <div class="blob" style="width: 600px; height: 600px; top: -200px; left: -100px;"></div>
        <div class="blob" style="width: 400px; height: 400px; bottom: -100px; right: 10%; background: var(--brand-navy); opacity: 0.05;"></div>
    </div>

    <div class="editorial-canvas">
        <div class="corner-deco"></div>

        <!-- Left Column -->
        <div class="brand-content">
            <div class="logo-section">
                <img src="{logo_url}" alt="Company Logo">
            </div>
            
            <div class="hero-title">
                <h1>{data.get('title', 'TEAM NIGHT').split()[0] if data.get('title') else 'TEAM'}<span>{data.get('title', 'NIGHT OUT').split()[-1] if data.get('title') else 'NIGHT'}</span></h1>
            </div>

            <div class="description">
                {data.get('company', 'Celebrating collective achievements and the people who make it possible.')}
            </div>
        </div>

        <!-- Right Column -->
        <div class="photo-side">
            <div class="photo-holder">
                <div class="photo-inner">
                    <img src="{image_url}" alt="Team Photo">
                </div>
                
                <div class="tag-container">
                    <div class="pill-tag teal-pill">{data.get('date', '2024').split('-')[0] if '-' in data.get('date', '2024') else data.get('date', '2024')}</div>
                    <div class="pill-tag">CULTURE FIRST</div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>"""
    
    # Template 7 HTML (Neo-Geometric Brand Experience)
    elif template_num == 7:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Neo-Geometric Brand Experience</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Syncopate:wght@700&family=Work+Sans:wght@300;600;900&display=swap');

        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #1A2B3C;
            --brand-white: #FFFFFF;
            --brand-bg: #0f172a;
        }}

        body {{
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: var(--brand-bg);
            font-family: 'Work Sans', sans-serif;
            overflow: hidden;
        }}

        /* Shattered Background Elements */
        .shard-container {{
            position: absolute;
            width: 100%;
            height: 100%;
            z-index: 0;
            overflow: hidden;
        }}

        .shard {{
            position: absolute;
            background: var(--brand-teal);
            opacity: 0.1;
            clip-path: polygon(50% 0%, 100% 100%, 0% 100%);
        }}

        /* Main Modular Canvas */
        .modular-canvas {{
            position: relative;
            width: 95vw;
            max-width: 1100px;
            height: 700px;
            display: flex;
            flex-direction: column;
            z-index: 10;
        }}

        /* Top Branding Header */
        .top-bar {{
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            padding: 0 40px 20px;
        }}

        .logo-wrap {{
            background: var(--brand-white);
            padding: 20px;
            clip-path: polygon(0 0, 100% 0, 85% 100%, 0% 100%);
        }}

        .logo-wrap img {{
            height: 60px;
            width: auto;
        }}

        .status-tag {{
            color: var(--brand-teal);
            font-family: 'Syncopate', sans-serif;
            font-size: 12px;
            letter-spacing: 4px;
            border-bottom: 2px solid var(--brand-teal);
            padding-bottom: 5px;
        }}

        /* Image Display with "Broken" Frame */
        .image-deck {{
            position: relative;
            flex-grow: 1;
            margin: 0 40px;
        }}

        .image-deck::before {{
            content: "";
            position: absolute;
            top: -20px;
            left: -20px;
            width: 100px;
            height: 100px;
            border-top: 4px solid var(--brand-teal);
            border-left: 4px solid var(--brand-teal);
        }}

        .main-photo {{
            width: 100%;
            height: 100%;
            background: var(--brand-navy);
            padding: 10px;
            box-sizing: border-box;
            border-radius: 4px;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
        }}

        .main-photo img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            opacity: 0.9;
            transition: opacity 0.3s ease;
        }}

        .main-photo:hover img {{
            opacity: 1;
        }}

        /* Hero Text Typography */
        .hero-text {{
            position: absolute;
            bottom: -50px;
            left: -20px;
            z-index: 20;
        }}

        .hero-text h1 {{
            font-family: 'Syncopate', sans-serif;
            font-size: 80px;
            color: var(--brand-white);
            margin: 0;
            line-height: 0.8;
            -webkit-text-stroke: 1px rgba(255,255,255,0.3);
            text-shadow: 10px 10px 0px var(--brand-navy);
        }}

        .hero-text h1 span {{
            color: var(--brand-teal);
            -webkit-text-stroke: 0;
        }}

        /* Bottom Stats Bar */
        .bottom-details {{
            display: flex;
            justify-content: flex-end;
            padding: 60px 40px 0;
            gap: 40px;
        }}

        .detail-item {{
            color: var(--brand-white);
            border-left: 2px solid var(--brand-teal);
            padding-left: 15px;
        }}

        .detail-item label {{
            display: block;
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 2px;
            color: var(--brand-teal);
            margin-bottom: 5px;
        }}

        .detail-item value {{
            font-weight: 900;
            font-size: 18px;
        }}

        /* Floating Accent Line */
        .accent-line {{
            position: absolute;
            right: 0;
            top: 50%;
            width: 300px;
            height: 2px;
            background: linear-gradient(90deg, transparent, var(--brand-teal));
        }}
    </style>
</head>
<body>
    <div class="shard-container">
        <div class="shard" style="width: 400px; height: 600px; top: -100px; right: -50px; transform: rotate(15deg);"></div>
        <div class="shard" style="width: 300px; height: 300px; bottom: 50px; left: -50px; transform: rotate(-25deg); opacity: 0.05;"></div>
    </div>

    <div class="modular-canvas">
        <!-- Top Branding -->
        <div class="top-bar">
            <div class="logo-wrap">
                <img src="{logo_url}" alt="Company Logo">
            </div>
            <div class="status-tag">CORE MOMENTS</div>
        </div>

        <!-- Main Photo Deck -->
        <div class="image-deck">
            <div class="main-photo">
                <img src="{image_url}" alt="Team Photo">
            </div>
            
            <div class="hero-text">
                <h1>{data.get('title', 'TEAM').split()[0] if data.get('title') else 'TEAM'}<br><span>{data.get('title', 'NIGHT').split()[-1] if data.get('title') else 'NIGHT'}</span></h1>
            </div>

            <div class="accent-line"></div>
        </div>

        <!-- Meta Footer -->
        <div class="bottom-details">
            <div class="detail-item">
                <label>Event Type</label>
                <value>{data.get('title', 'SOCIAL GATHERING')}</value>
            </div>
            <div class="detail-item">
                <label>Location</label>
                <value>{data.get('company', 'CITY CENTER')}</value>
            </div>
            <div class="detail-item">
                <label>Timeline</label>
                <value>Q4 - {data.get('date', '2024').split('-')[0] if '-' in data.get('date', '2024') else data.get('date', '2024')}</value>
            </div>
        </div>
    </div>
</body>
</html>"""
    
    # Template 8 HTML (Perspective Grid Brand Experience)
    elif template_num == 8:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Perspective Grid Brand Experience</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@200;900&family=Space+Grotesk:wght@300;700&display=swap');

        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #1A2B3C;
            --brand-white: #FFFFFF;
            --brand-bg: #0b1118;
        }}

        body {{
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: var(--brand-bg);
            font-family: 'Space Grotesk', sans-serif;
            overflow: hidden;
            color: var(--brand-white);
        }}

        /* Perspective Grid Background */
        .grid-bg {{
            position: absolute;
            width: 200%;
            height: 200%;
            background-image: 
                linear-gradient(rgba(76, 182, 167, 0.1) 1px, transparent 1px),
                linear-gradient(90deg, rgba(76, 182, 167, 0.1) 1px, transparent 1px);
            background-size: 50px 50px;
            transform: perspective(500px) rotateX(60deg) translateY(-200px);
            z-index: 0;
            animation: moveGrid 20s linear infinite;
        }}

        @keyframes moveGrid {{
            from {{ transform: perspective(500px) rotateX(60deg) translateY(-200px); }}
            to {{ transform: perspective(500px) rotateX(60deg) translateY(0px); }}
        }}

        /* Main Perspective Canvas */
        .canvas-container {{
            position: relative;
            width: 90vw;
            max-width: 1100px;
            height: 650px;
            z-index: 10;
            display: grid;
            grid-template-columns: 1fr 2fr;
            align-items: center;
            gap: 40px;
        }}

        /* Left Side: Dynamic Branding */
        .brand-panel {{
            position: relative;
            z-index: 20;
        }}

        .brand-tag {{
            display: inline-block;
            background: var(--brand-teal);
            color: var(--brand-navy);
            padding: 5px 15px;
            font-weight: 700;
            font-size: 12px;
            letter-spacing: 3px;
            text-transform: uppercase;
            margin-bottom: 20px;
        }}

        .main-title h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 90px;
            font-weight: 900;
            line-height: 0.8;
            margin: 0;
            letter-spacing: -2px;
            text-transform: uppercase;
        }}

        .main-title h1 span {{
            display: block;
            color: transparent;
            -webkit-text-stroke: 1.5px var(--brand-teal);
        }}

        .logo-box {{
            margin-top: 40px;
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(10px);
            padding: 20px;
            display: inline-block;
            border-left: 4px solid var(--brand-teal);
        }}

        .logo-box img {{
            height: 60px;
            width: auto;
        }}

        /* Right Side: 3D Photo Float */
        .photo-perspective {{
            position: relative;
            perspective: 1000px;
        }}

        .photo-card {{
            position: relative;
            width: 100%;
            background: var(--brand-navy);
            padding: 10px;
            border-radius: 4px;
            transform: rotateY(-15deg) rotateX(5deg);
            box-shadow: 30px 30px 60px rgba(0,0,0,0.5);
            transition: all 0.6s ease;
            border: 1px solid rgba(76, 182, 167, 0.3);
        }}

        .photo-card:hover {{
            transform: rotateY(0deg) rotateX(0deg) scale(1.05);
            box-shadow: 0 40px 80px rgba(0,0,0,0.6);
        }}

        .photo-card img {{
            width: 100%;
            height: auto;
            display: block;
            border-radius: 2px;
        }}

        /* Floating Meta Info */
        .meta-float {{
            position: absolute;
            bottom: -30px;
            left: -30px;
            background: var(--brand-white);
            color: var(--brand-navy);
            padding: 20px 30px;
            border-radius: 0;
            font-weight: 700;
            z-index: 30;
            box-shadow: 10px 10px 0 var(--brand-teal);
        }}

        .meta-float small {{
            display: block;
            font-size: 10px;
            letter-spacing: 2px;
            opacity: 0.6;
            margin-bottom: 5px;
        }}

        /* Deco Elements */
        .glow-orb {{
            position: absolute;
            width: 400px;
            height: 400px;
            background: radial-gradient(circle, rgba(76, 182, 167, 0.2) 0%, transparent 70%);
            top: 10%;
            right: 10%;
            z-index: 1;
        }}
    </style>
</head>
<body>
    <div class="grid-bg"></div>
    <div class="glow-orb"></div>

    <div class="canvas-container">
        <!-- Left Branding Panel -->
        <div class="brand-panel">
            <div class="brand-tag">Network • Unity</div>
            <div class="main-title">
                <h1>{data.get('title', 'TEAM NIGHT').split()[0] if data.get('title') else 'TEAM'}<span>{data.get('title', 'NIGHT OUT').split()[-1] if data.get('title') else 'NIGHT'}</span></h1>
            </div>
            
            <div class="logo-box">
                <img src="{logo_url}" alt="Logo">
            </div>
        </div>

        <!-- Right Perspective Photo -->
        <div class="photo-perspective">
            <div class="photo-card">
                <img src="{image_url}" alt="Team Night Out">
            </div>

            <div class="meta-float">
                <small>{data.get('company', 'CHAPTER 04')}</small>
                {data.get('name', 'LEVELING UP TOGETHER')}
            </div>
        </div>
    </div>
</body>
</html>"""
    
    # Template 9 HTML (Static Editorial Brand Frame)
    elif template_num == 9:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Static Editorial Brand Frame</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@900&family=Work+Sans:wght@300;800&display=swap');

        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #1A2B3C;
            --brand-white: #FFFFFF;
            --brand-bg: #f1f5f9;
        }}

        body {{
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: var(--brand-bg);
            font-family: 'Work Sans', sans-serif;
            overflow: hidden;
        }}

        /* Static Abstract Background */
        .canvas-bg {{
            position: absolute;
            width: 1000px;
            height: 700px;
            background: var(--brand-white);
            box-shadow: 0 40px 100px rgba(0,0,0,0.1);
            overflow: hidden;
            z-index: 0;
        }}

        .bg-stripe {{
            position: absolute;
            top: 0;
            right: 0;
            width: 38%; /* Slightly widened for better text containment */
            height: 100%;
            background: var(--brand-navy);
        }}

        .bg-accent-block {{
            position: absolute;
            bottom: 0;
            left: 0;
            width: 100%;
            height: 150px;
            background: var(--brand-teal);
            opacity: 0.1;
        }}

        /* Main Content Grid */
        .content-wrap {{
            position: relative;
            width: 1000px;
            height: 700px;
            z-index: 10;
            display: grid;
            grid-template-columns: 1.1fr 1fr; /* Adjusted ratio */
            padding: 50px;
            box-sizing: border-box;
        }}

        /* Left Side: Photo & Creative Border */
        .photo-area {{
            position: relative;
            display: flex;
            align-items: center;
        }}

        .photo-frame {{
            position: relative;
            width: 115%; /* Deeper overlap into the navy section */
            background: var(--brand-white);
            padding: 12px;
            box-shadow: 25px 25px 0 var(--brand-teal);
            z-index: 20;
            border-radius: 2px;
        }}

        .photo-frame img {{
            width: 100%;
            height: auto;
            display: block;
            border: 1px solid #f0f0f0;
        }}

        /* Right Side: Typography & Logo */
        .info-area {{
            position: relative;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            padding-left: 80px; /* Increased padding for breathing room */
            z-index: 30;
            color: var(--brand-white);
        }}

        .logo-box {{
            align-self: flex-end;
            background: var(--brand-white);
            padding: 18px 25px;
            box-shadow: 0 15px 35px rgba(0,0,0,0.3);
            border-radius: 2px;
        }}

        .logo-box img {{
            height: 65px;
            width: auto;
        }}

        .text-block {{
            margin-bottom: 50px;
        }}

        .text-block h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 82px; /* Slightly refined size for export clarity */
            line-height: 0.85;
            margin: 0;
            text-transform: uppercase;
            letter-spacing: -3px;
        }}

        .text-block h1 span {{
            color: var(--brand-teal);
            display: block;
        }}

        .tagline {{
            margin-top: 25px;
            font-size: 13px;
            font-weight: 800;
            letter-spacing: 5px;
            text-transform: uppercase;
            color: var(--brand-teal);
            border-bottom: 3px solid var(--brand-teal);
            display: inline-block;
            padding-bottom: 6px;
        }}

        /* Decorative Elements (Static) */
        .geo-dot {{
            position: absolute;
            top: 40px;
            left: 40px;
            width: 18px;
            height: 18px;
            background: var(--brand-teal);
            border-radius: 50%;
        }}

        .geo-line {{
            position: absolute;
            bottom: 40px;
            right: 40px;
            width: 80px;
            height: 4px;
            background: var(--brand-teal); /* Changed to teal for consistency */
        }}

        .accent-corner {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100px;
            height: 100px;
            background: linear-gradient(135deg, var(--brand-teal) 15%, transparent 15%);
        }}
    </style>
</head>
<body>
    <div class="canvas-bg">
        <div class="accent-corner"></div>
        <div class="bg-stripe"></div>
        <div class="bg-accent-block"></div>
        <div class="geo-dot"></div>
        
        <div class="content-wrap">
            <!-- Image Section -->
            <div class="photo-area">
                <div class="photo-frame">
                    <img src="{image_url}" alt="Team Night Out">
                </div>
            </div>

            <!-- Branding Section -->
            <div class="info-area">
                <div class="logo-box">
                    <img src="{logo_url}" alt="Company Logo">
                </div>

                <div class="text-block">
                    <h1>{data.get('title', 'TEAM NIGHT').split()[0] if data.get('title') else 'TEAM'}<span>{data.get('title', 'NIGHT OUT').split()[-1] if data.get('title') else 'NIGHT'}</span></h1>
                    <div class="tagline">{data.get('company', 'UNITED BY PURPOSE')}</div>
                </div>
            </div>
        </div>
        
        <div class="geo-line"></div>
    </div>
</body>
</html>"""
    
    # Template 10 HTML (Modern Glass Pane Brand Frame)
    elif template_num == 10:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Modern Glass Pane Brand Frame</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@900&family=Work+Sans:wght@300;800&display=swap');

        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #1A2B3C;
            --brand-white: #FFFFFF;
            --brand-bg: #f1f5f9;
        }}

        body {{
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: var(--brand-bg);
            font-family: 'Work Sans', sans-serif;
            overflow: hidden;
        }}

        /* Large Format Canvas - Minimal Padding */
        .canvas-container {{
            position: relative;
            width: 1150px;
            height: 750px;
            background: var(--brand-white);
            box-shadow: 0 50px 100px rgba(0,0,0,0.12);
            padding: 15px;
            box-sizing: border-box;
            display: grid;
            grid-template-columns: 320px 1fr;
            gap: 15px;
        }}

        /* Left Branding Column */
        .brand-sidebar {{
            background: var(--brand-navy);
            border-radius: 12px;
            padding: 40px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            color: var(--brand-white);
            position: relative;
            overflow: hidden;
        }}

        /* Decorative Background for Sidebar */
        .brand-sidebar::before {{
            content: "";
            position: absolute;
            top: -50px;
            left: -50px;
            width: 200px;
            height: 200px;
            background: var(--brand-teal);
            opacity: 0.1;
            border-radius: 50%;
        }}

        .logo-area {{
            background: var(--brand-white);
            padding: 25px;
            border-radius: 8px;
            display: flex;
            justify-content: center;
            align-items: center;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }}

        .logo-area img {{
            width: 100%;
            height: auto;
            max-height: 80px;
            object-fit: contain;
        }}

        .sidebar-footer h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 56px;
            line-height: 0.9;
            margin: 0;
            text-transform: uppercase;
        }}

        .sidebar-footer h1 span {{
            color: var(--brand-teal);
            display: block;
        }}

        .sidebar-footer p {{
            margin-top: 20px;
            font-size: 14px;
            letter-spacing: 3px;
            text-transform: uppercase;
            color: var(--brand-teal);
            font-weight: 800;
        }}

        /* Massive Immersive Photo Area */
        .photo-main {{
            position: relative;
            border-radius: 12px;
            overflow: hidden;
            background: #eee;
        }}

        .photo-main img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }}

        /* Subtle Floating Info */
        .info-pill {{
            position: absolute;
            top: 30px;
            right: 30px;
            background: rgba(26, 43, 60, 0.8);
            backdrop-filter: blur(10px);
            padding: 10px 25px;
            border-radius: 50px;
            color: var(--brand-white);
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 1px;
            border: 1px solid rgba(255,255,255,0.1);
        }}

        /* Geometric Static Accents */
        .teal-corner {{
            position: absolute;
            bottom: 0;
            right: 0;
            width: 80px;
            height: 80px;
            background: linear-gradient(135deg, transparent 50%, var(--brand-teal) 50%);
        }}

        .accent-lines {{
            position: absolute;
            bottom: 40px;
            left: 40px;
            display: flex;
            gap: 8px;
        }}

        .line {{
            width: 4px;
            height: 40px;
            background: var(--brand-teal);
            border-radius: 2px;
        }}
    </style>
</head>
<body>
    <div class="canvas-container">
        <!-- Branding Sidebar -->
        <div class="brand-sidebar">
            <div class="logo-area">
                <img src="{logo_url}" alt="Company Logo">
            </div>

            <div class="sidebar-footer">
                <h1>{data.get('title', 'TEAM NIGHT').split()[0] if data.get('title') else 'TEAM'}<span>{data.get('title', 'NIGHT OUT').split()[-1] if data.get('title') else 'NIGHT'}</span></h1>
                <p>{data.get('date', '2024 Edition')}</p>
                <div style="width: 50px; height: 4px; background: var(--brand-teal); margin-top: 15px;"></div>
            </div>
        </div>

        <!-- The Photo (Maximizing Area) -->
        <div class="photo-main">
            <img src="{image_url}" alt="Team Night Out">
            
            <div class="info-pill">{data.get('company', 'CULTURE & COMMUNITY')}</div>
            
            <div class="accent-lines">
                <div class="line"></div>
                <div class="line" style="opacity: 0.6; height: 30px; margin-top: 10px;"></div>
                <div class="line" style="opacity: 0.3; height: 20px; margin-top: 20px;"></div>
            </div>

            <div class="teal-corner"></div>
        </div>
    </div>
</body>
</html>"""
    
    # Template 11 HTML (Architectural Frame Design)
    elif template_num == 11:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Architectural Frame Design</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@900&family=Work+Sans:wght@300;800&display=swap');

        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #0A1622;
            --brand-white: #FFFFFF;
            --brand-bg: #e2e8f0;
        }}

        body {{
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: var(--brand-bg);
            font-family: 'Work Sans', sans-serif;
            overflow: hidden;
        }}

        /* Large Format Canvas */
        .canvas-container {{
            position: relative;
            width: 1150px;
            height: 750px;
            background: var(--brand-navy);
            box-shadow: 0 60px 120px rgba(0,0,0,0.4);
            display: grid;
            grid-template-columns: 100px 1fr 100px;
            grid-template-rows: 100px 1fr 100px;
            overflow: hidden;
        }}

        /* The Main Image (Architectural Cutout) */
        .photo-central {{
            grid-column: 2 / 3;
            grid-row: 1 / 4;
            position: relative;
            z-index: 1;
            padding: 20px 0;
        }}

        .photo-central img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
            border-left: 2px solid var(--brand-teal);
            border-right: 2px solid var(--brand-teal);
        }}

        /* Branding Blocks */
        .brand-block-top {{
            grid-column: 1 / 2;
            grid-row: 1 / 2;
            background: var(--brand-white);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 10;
        }}

        .brand-block-top img {{
            width: 60%;
            height: auto;
        }}

        .brand-block-bottom {{
            grid-column: 3 / 4;
            grid-row: 3 / 4;
            background: var(--brand-teal);
            z-index: 10;
            display: flex;
            justify-content: center;
            align-items: center;
            color: var(--brand-navy);
            font-weight: 900;
            font-size: 24px;
        }}

        /* Typography Overlay */
        .text-overlay {{
            position: absolute;
            bottom: 60px;
            left: 40px;
            z-index: 20;
            pointer-events: none;
        }}

        .text-overlay h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 110px;
            line-height: 0.8;
            margin: 0;
            color: var(--brand-white);
            text-transform: uppercase;
            letter-spacing: -5px;
            text-shadow: 15px 15px 0px var(--brand-navy);
        }}

        .text-overlay h1 span {{
            color: var(--brand-teal);
            display: block;
            padding-left: 40px;
        }}

        /* Static Decors */
        .side-label {{
            grid-column: 3 / 4;
            grid-row: 1 / 3;
            writing-mode: vertical-rl;
            display: flex;
            justify-content: center;
            align-items: center;
            color: var(--brand-white);
            opacity: 0.2;
            font-size: 12px;
            letter-spacing: 10px;
            text-transform: uppercase;
        }}

        .bottom-stripe {{
            position: absolute;
            bottom: 0;
            left: 100px;
            width: calc(100% - 200px);
            height: 20px;
            background: var(--brand-teal);
            z-index: 5;
        }}

        .pattern-box {{
            grid-column: 1 / 2;
            grid-row: 3 / 4;
            background-image: radial-gradient(var(--brand-teal) 2px, transparent 2px);
            background-size: 10px 10px;
            opacity: 0.3;
        }}
    </style>
</head>
<body>
    <div class="canvas-container">
        <!-- Structural Branding Blocks -->
        <div class="brand-block-top">
            <img src="{logo_url}" alt="Logo">
        </div>
        
        <div class="side-label">CULTURE • UNITY • {data.get('date', '2024').split('-')[0] if '-' in data.get('date', '2024') else data.get('date', '2024')}</div>
        
        <div class="pattern-box"></div>
        
        <div class="brand-block-bottom">
            {data.get('date', '2024').split('-')[0][-2:] if '-' in data.get('date', '2024') else data.get('date', '2024')[-2:]}
        </div>

        <!-- Central Immersive Photo -->
        <div class="photo-central">
            <img src="{image_url}" alt="Team Photo">
        </div>

        <!-- Bold Text Hierarchy -->
        <div class="text-overlay">
            <h1>{data.get('title', 'TEAM').split()[0] if data.get('title') else 'TEAM'}<span>{data.get('title', 'NIGHT').split()[-1] if data.get('title') else 'NIGHT'}</span></h1>
        </div>

        <div class="bottom-stripe"></div>
    </div>
</body>
</html>"""
    
    # Template 12 HTML (Layered Monument Brand Frame)
    elif template_num == 12:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Layered Monument Brand Frame</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@900&family=Work+Sans:wght@300;800&display=swap');

        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #1A2B3C;
            --brand-white: #FFFFFF;
            --brand-bg: #f1f5f9;
        }}

        body {{
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: var(--brand-bg);
            font-family: 'Work Sans', sans-serif;
            overflow: hidden;
        }}

        /* Large Format Canvas */
        .canvas-container {{
            position: relative;
            width: 1150px;
            height: 750px;
            background: var(--brand-white);
            box-shadow: 0 50px 100px rgba(0,0,0,0.12);
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }}

        /* Background Deco - Static */
        .bg-accent {{
            position: absolute;
            top: 0;
            right: 0;
            width: 40%; /* Reduced slightly to give photo more horizontal room */
            height: 100%;
            background: var(--brand-navy);
            z-index: 1;
        }}

        /* Content Layout */
        .main-layout {{
            position: relative;
            z-index: 10;
            display: grid;
            grid-template-columns: 1fr 380px;
            height: 100%;
            padding: 25px; /* Reduced outer padding */
            box-sizing: border-box;
            gap: 30px;
        }}

        /* Large Image Section */
        .photo-section {{
            position: relative;
            height: 100%;
            display: flex;
            align-items: center;
        }}

        .photo-wrap {{
            position: relative;
            width: 100%;
            height: 96%; /* Increased height to fill more area */
            background: var(--brand-white);
            padding: 6px; /* Reduced frame border thickness */
            box-shadow: 15px 15px 0 var(--brand-teal); /* Slightly smaller shadow for tighter feel */
            box-sizing: border-box;
        }}

        .photo-wrap img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }}

        /* Branding Column */
        .branding-section {{
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            color: var(--brand-white);
            padding: 20px 0;
        }}

        .logo-area {{
            background: var(--brand-white);
            padding: 20px;
            display: inline-block;
            align-self: flex-start;
            box-shadow: 0 15px 30px rgba(0,0,0,0.2);
        }}

        .logo-area img {{
            height: 55px;
            width: auto;
        }}

        .title-area h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 78px; /* Slightly adjusted to fit new column width */
            line-height: 0.8;
            margin: 0;
            text-transform: uppercase;
            letter-spacing: -3px;
        }}

        .title-area h1 span {{
            color: var(--brand-teal);
            display: block;
        }}

        .tagline {{
            margin-top: 30px;
            font-size: 14px;
            font-weight: 800;
            letter-spacing: 5px;
            color: var(--brand-teal);
            text-transform: uppercase;
            border-left: 4px solid var(--brand-teal);
            padding-left: 15px;
        }}

        /* Abstract Static Decor */
        .deco-dots {{
            position: absolute;
            bottom: 30px;
            left: 30px;
            width: 100px;
            height: 40px;
            background-image: radial-gradient(var(--brand-navy) 2px, transparent 2px);
            background-size: 12px 12px;
            opacity: 0.2;
        }}

        .vertical-label {{
            position: absolute;
            top: 50%;
            right: 15px;
            transform: translateY(-50%) rotate(90deg);
            font-family: 'Outfit', sans-serif;
            font-size: 11px;
            letter-spacing: 8px;
            color: rgba(255,255,255,0.2);
            text-transform: uppercase;
            white-space: nowrap;
        }}
    </style>
</head>
<body>
    <div class="canvas-container">
        <div class="bg-accent"></div>
        <div class="vertical-label">COMMUNITY AND CULTURE {data.get('date', '2024').split('-')[0] if '-' in data.get('date', '2024') else data.get('date', '2024')}</div>
        <div class="deco-dots"></div>

        <div class="main-layout">
            <!-- Massive Photo Section -->
            <div class="photo-section">
                <div class="photo-wrap">
                    <img src="{image_url}" alt="Team Night Out">
                </div>
            </div>

            <!-- Solid Branding Section -->
            <div class="branding-section">
                <div class="logo-area">
                    <img src="{logo_url}" alt="Company Logo">
                </div>

                <div class="title-area">
                    <h1>{data.get('title', 'TEAM NIGHT').split()[0] if data.get('title') else 'TEAM'}<span>{data.get('title', 'NIGHT OUT').split()[-1] if data.get('title') else 'NIGHT'}</span></h1>
                    <div class="tagline">{data.get('company', 'UNITED BY MOMENTS')}</div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>"""
    
    # Template 13 HTML (Brand Team Frame)
    elif template_num == 13:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Brand Team Frame</title>
    <style>
        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #1A2B3C;
            --brand-white: #FFFFFF;
        }}

        body {{
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: #e9ecef;
            margin: 0;
            font-family: 'Helvetica Neue', Arial, sans-serif;
        }}

        /* Main Canvas */
        .brand-frame {{
            position: relative;
            width: 900px;
            height: 650px;
            background-color: var(--brand-white);
            padding: 40px;
            box-sizing: border-box;
            border-bottom: 15px solid var(--brand-navy);
            box-shadow: 0 20px 40px rgba(0,0,0,0.15);
            display: flex;
            flex-direction: column;
            align-items: center;
        }}

        /* Top Corner Accents */
        .brand-frame::before {{
            content: "";
            position: absolute;
            top: 0; right: 0;
            width: 150px; height: 150px;
            background: linear-gradient(135deg, transparent 50%, var(--brand-teal) 50%);
        }}

        /* Image Container */
        .photo-wrapper {{
            position: relative;
            width: 100%;
            height: 480px;
            border: 8px solid var(--brand-navy);
            overflow: hidden;
            z-index: 2;
        }}

        .photo-wrapper img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
        }}

        /* Bottom Branding Bar */
        .footer {{
            width: 100%;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 25px;
        }}

        .logo-container img {{
            height: 60px; /* Adjust logo size */
            width: auto;
        }}

        .text-content {{
            text-align: right;
        }}

        .text-content h1 {{
            margin: 0;
            color: var(--brand-navy);
            font-size: 28px;
            letter-spacing: 1px;
        }}

        .text-content p {{
            margin: 5px 0 0;
            color: var(--brand-teal);
            font-weight: bold;
            text-transform: uppercase;
            font-size: 14px;
        }}

        /* Abstract Teal shape behind logo */
        .accent-circle {{
            position: absolute;
            bottom: -20px;
            left: -20px;
            width: 120px;
            height: 120px;
            background-color: var(--brand-teal);
            border-radius: 50%;
            opacity: 0.2;
            z-index: 1;
        }}
    </style>
</head>
<body>
    <div class="brand-frame">
        <div class="accent-circle"></div>

        <div class="photo-wrapper">
            <img src="{image_url}" alt="Company Team">
        </div>

        <div class="footer">
            <div class="logo-container">
                <img src="{logo_url}" alt="Company Logo">
            </div>
            
            <div class="text-content">
                <h1>{data.get('title', 'OUR TEAM NIGHT OUT')}</h1>
                <p>{data.get('company', 'Building the Future Together')}</p>
            </div>
        </div>
    </div>
</body>
</html>"""
    
    # Template 14 HTML (Layered Monument Brand Frame - Alternative)
    elif template_num == 14:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Layered Monument Brand Frame</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@900&family=Work+Sans:wght@300;800&display=swap');

        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #1A2B3C;
            --brand-white: #FFFFFF;
            --brand-bg: #f1f5f9;
        }}

        body {{
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: var(--brand-bg);
            font-family: 'Work Sans', sans-serif;
            overflow: hidden;
        }}

        /* Large Format Canvas */
        .canvas-container {{
            position: relative;
            width: 1150px;
            height: 750px;
            background: var(--brand-white);
            box-shadow: 0 50px 100px rgba(0,0,0,0.12);
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }}

        /* Background Deco - Static */
        .bg-accent {{
            position: absolute;
            top: 0;
            right: 0;
            width: 45%;
            height: 100%;
            background: var(--brand-navy);
            z-index: 1;
        }}

        /* Content Layout */
        .main-layout {{
            position: relative;
            z-index: 10;
            display: grid;
            grid-template-columns: 1fr 400px;
            height: 100%;
            padding: 40px;
            box-sizing: border-box;
            gap: 40px;
        }}

        /* Large Image Section */
        .photo-section {{
            position: relative;
            height: 100%;
            display: flex;
            align-items: center;
        }}

        .photo-wrap {{
            position: relative;
            width: 100%;
            height: 90%;
            background: var(--brand-white);
            padding: 12px;
            box-shadow: 20px 20px 0 var(--brand-teal);
            box-sizing: border-box;
        }}

        .photo-wrap img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }}

        /* Branding Column */
        .branding-section {{
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            color: var(--brand-white);
            padding: 20px 0;
        }}

        .logo-area {{
            background: var(--brand-white);
            padding: 25px;
            display: inline-block;
            align-self: flex-start;
            box-shadow: 0 15px 30px rgba(0,0,0,0.2);
        }}

        .logo-area img {{
            height: 60px;
            width: auto;
        }}

        .title-area h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 82px;
            line-height: 0.8;
            margin: 0;
            text-transform: uppercase;
            letter-spacing: -3px;
        }}

        .title-area h1 span {{
            color: var(--brand-teal);
            display: block;
        }}

        .tagline {{
            margin-top: 30px;
            font-size: 14px;
            font-weight: 800;
            letter-spacing: 5px;
            color: var(--brand-teal);
            text-transform: uppercase;
            border-left: 4px solid var(--brand-teal);
            padding-left: 15px;
        }}

        /* Abstract Static Decor */
        .deco-dots {{
            position: absolute;
            bottom: 40px;
            left: 40px;
            width: 100px;
            height: 40px;
            background-image: radial-gradient(var(--brand-navy) 2px, transparent 2px);
            background-size: 12px 12px;
            opacity: 0.2;
        }}

        .vertical-label {{
            position: absolute;
            top: 50%;
            right: 20px;
            transform: translateY(-50%) rotate(90deg);
            font-family: 'Outfit', sans-serif;
            font-size: 12px;
            letter-spacing: 8px;
            color: rgba(255,255,255,0.2);
            text-transform: uppercase;
            white-space: nowrap;
        }}
    </style>
</head>
<body>
    <div class="canvas-container">
        <div class="bg-accent"></div>
        <div class="vertical-label">COMMUNITY AND CULTURE {data.get('date', '2024').split('-')[0] if '-' in data.get('date', '2024') else data.get('date', '2024')}</div>
        <div class="deco-dots"></div>

        <div class="main-layout">
            <!-- Massive Photo Section -->
            <div class="photo-section">
                <div class="photo-wrap">
                    <img src="{image_url}" alt="Team Night Out">
                </div>
            </div>

            <!-- Solid Branding Section -->
            <div class="branding-section">
                <div class="logo-area">
                    <img src="{logo_url}" alt="Company Logo">
                </div>

                <div class="title-area">
                    <h1>{data.get('title', 'TEAM NIGHT').split()[0] if data.get('title') else 'TEAM'}<span>{data.get('title', 'NIGHT OUT').split()[-1] if data.get('title') else 'NIGHT'}</span></h1>
                    <div class="tagline">{data.get('company', 'UNITED BY MOMENTS')}</div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>"""
    
    # Template 15 HTML (Dynamic Border-Block Design)
    elif template_num == 15:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dynamic Border-Block Design</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@900&family=Work+Sans:wght@300;800&display=swap');

        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #0A1622;
            --brand-white: #FFFFFF;
            --brand-bg: #e2e8f0;
        }}

        body {{
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: var(--brand-bg);
            font-family: 'Work Sans', sans-serif;
            overflow: hidden;
        }}

        /* Large Format Canvas */
        .canvas-container {{
            position: relative;
            width: 1150px;
            height: 750px;
            background: var(--brand-navy);
            box-shadow: 0 70px 140px rgba(0,0,0,0.4);
            display: flex;
            justify-content: center;
            align-items: center;
            overflow: hidden;
        }}

        /* Thick Internal Frame */
        .internal-frame {{
            position: absolute;
            top: 40px;
            left: 40px;
            right: 40px;
            bottom: 40px;
            border: 2px solid rgba(76, 182, 167, 0.3);
            pointer-events: none;
            z-index: 5;
        }}

        /* Main Image Container - Maximized Area */
        .photo-canvas {{
            position: relative;
            width: 85%;
            height: 80%;
            background: var(--brand-white);
            padding: 15px;
            z-index: 10;
            box-shadow: 0 40px 80px rgba(0,0,0,0.5);
            display: flex;
        }}

        .photo-canvas img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }}

        /* Branding Overlays */
        .logo-badge {{
            position: absolute;
            top: -30px;
            right: 60px;
            background: var(--brand-white);
            padding: 25px;
            z-index: 30;
            box-shadow: 0 20px 40px rgba(0,0,0,0.2);
        }}

        .logo-badge img {{
            height: 50px;
            width: auto;
        }}

        .typography-box {{
            position: absolute;
            bottom: -50px;
            left: -40px;
            z-index: 40;
        }}

        .typography-box h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 110px;
            line-height: 0.8;
            margin: 0;
            color: var(--brand-white);
            text-transform: uppercase;
            letter-spacing: -4px;
            text-shadow: 10px 10px 0 var(--brand-navy);
        }}

        .typography-box h1 span {{
            color: var(--brand-teal);
            display: block;
            padding-left: 60px;
        }}

        /* Sub-details Badge */
        .details-pill {{
            position: absolute;
            bottom: 60px;
            right: -20px;
            background: var(--brand-teal);
            color: var(--brand-navy);
            padding: 12px 30px;
            font-weight: 900;
            font-size: 14px;
            letter-spacing: 3px;
            text-transform: uppercase;
            transform: rotate(-90deg);
            transform-origin: right bottom;
            z-index: 50;
        }}

        /* Static Decors */
        .top-left-accent {{
            position: absolute;
            top: 0;
            left: 0;
            width: 150px;
            height: 150px;
            background: linear-gradient(135deg, var(--brand-teal) 0%, transparent 70%);
            opacity: 0.2;
        }}

        .bottom-right-stripe {{
            position: absolute;
            bottom: 40px;
            right: 40px;
            width: 100px;
            height: 4px;
            background: var(--brand-teal);
            z-index: 5;
        }}

        .year-vertical {{
            position: absolute;
            top: 50%;
            left: 15px;
            transform: translateY(-50%);
            writing-mode: vertical-rl;
            color: var(--brand-white);
            font-family: 'Outfit', sans-serif;
            font-size: 40px;
            font-weight: 900;
            opacity: 0.05;
        }}
    </style>
</head>
<body>
    <div class="canvas-container">
        <div class="top-left-accent"></div>
        <div class="internal-frame"></div>
        <div class="year-vertical">MOMENTS {data.get('date', '2024').split('-')[0] if '-' in data.get('date', '2024') else data.get('date', '2024')}</div>
        
        <div class="photo-canvas">
            <img src="{image_url}" alt="Team Photo">
            
            <!-- Branding elements that overlap the photo -->
            <div class="logo-badge">
                <img src="{logo_url}" alt="Logo">
            </div>

            <div class="typography-box">
                <h1>{data.get('title', 'TEAM').split()[0] if data.get('title') else 'TEAM'}<span>{data.get('title', 'NIGHT').split()[-1] if data.get('title') else 'NIGHT'}</span></h1>
            </div>

            <div class="details-pill">{data.get('company', 'CHAPTER 04')} • CULTURE</div>
        </div>

        <div class="bottom-right-stripe"></div>
    </div>
</body>
</html>"""
    
    # Template 16 HTML (Tech Circuit-Board Frame)
    elif template_num == 16:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tech Circuit-Board Frame</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@900&family=Work+Sans:wght@300;800&family=JetBrains+Mono:wght@400;700&display=swap');

        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #0A1622;
            --brand-white: #FFFFFF;
            --brand-bg: #050a0f;
            --node-glow: rgba(76, 182, 167, 0.6);
        }}

        body {{
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: var(--brand-bg);
            font-family: 'Work Sans', sans-serif;
            overflow: hidden;
        }}

        /* Large Format Canvas */
        .canvas-container {{
            position: relative;
            width: 1150px;
            height: 750px;
            background: radial-gradient(circle at center, #112233 0%, var(--brand-navy) 100%);
            box-shadow: 0 0 100px rgba(0,0,0,0.8);
            overflow: hidden;
        }}

        /* Circuit Trace Background */
        .circuit-bg {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            opacity: 0.15;
            z-index: 1;
        }}

        /* The Main Image Frame */
        .image-outer-frame {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 900px;
            height: 550px;
            z-index: 10;
            background: var(--brand-teal);
            padding: 1px; /* The ultra-fine teal border */
            box-shadow: 0 0 50px rgba(0,0,0,0.5);
        }}

        .image-inner {{
            width: 100%;
            height: 100%;
            background: var(--brand-white);
            overflow: hidden;
            position: relative;
        }}

        .image-inner img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }}

        /* Circuit Nodes & Lines */
        .node {{
            position: absolute;
            width: 8px;
            height: 8px;
            background: var(--brand-teal);
            border-radius: 50%;
            box-shadow: 0 0 10px var(--node-glow);
            z-index: 20;
        }}

        .trace-line {{
            position: absolute;
            background: var(--brand-teal);
            opacity: 0.4;
            z-index: 15;
        }}

        /* Branding: Top Left Corner */
        .logo-block {{
            position: absolute;
            top: 40px;
            left: 40px;
            z-index: 30;
            background: var(--brand-white);
            padding: 15px 25px;
            border-bottom: 4px solid var(--brand-teal);
        }}

        .logo-block img {{
            height: 40px;
            width: auto;
        }}

        /* Tech Header Typography */
        .header-text {{
            position: absolute;
            top: 40px;
            right: 60px;
            text-align: right;
            z-index: 30;
        }}

        .header-text h2 {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 14px;
            letter-spacing: 5px;
            color: var(--brand-teal);
            margin: 0;
            text-transform: uppercase;
        }}

        /* Bottom Hero Typography */
        .hero-text {{
            position: absolute;
            bottom: 40px;
            left: 60px;
            z-index: 30;
        }}

        .hero-text h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 90px;
            line-height: 0.8;
            margin: 0;
            color: var(--brand-white);
            text-transform: uppercase;
            letter-spacing: -3px;
        }}

        .hero-text h1 span {{
            color: var(--brand-teal);
            display: block;
            padding-left: 50px;
            font-size: 70px;
        }}

        /* Metadata Badge */
        .meta-badge {{
            position: absolute;
            bottom: 60px;
            right: 60px;
            font-family: 'JetBrains Mono', monospace;
            background: rgba(76, 182, 167, 0.1);
            border: 1px solid var(--brand-teal);
            padding: 15px 25px;
            color: var(--brand-white);
            z-index: 30;
        }}

        .meta-badge div {{
            font-size: 10px;
            letter-spacing: 2px;
            margin-bottom: 4px;
            opacity: 0.7;
        }}

        .meta-badge strong {{
            font-size: 14px;
            color: var(--brand-teal);
        }}
    </style>
</head>
<body>
    <div class="canvas-container">
        <!-- Background Elements -->
        <div class="circuit-bg">
            <!-- Simulated Trace Lines -->
            <div class="trace-line" style="top: 100px; left: 0; width: 300px; height: 1px;"></div>
            <div class="trace-line" style="bottom: 150px; right: 0; width: 400px; height: 1px;"></div>
            <div class="trace-line" style="top: 0; left: 500px; width: 1px; height: 200px;"></div>
        </div>
        
        <!-- Corner Nodes -->
        <div class="node" style="top: 100px; left: 300px;"></div>
        <div class="node" style="bottom: 150px; right: 400px;"></div>
        <div class="node" style="top: 200px; left: 500px;"></div>

        <!-- Identity Elements -->
        <div class="logo-block">
            <img src="{logo_url}" alt="Logo">
        </div>

        <div class="header-text">
            <h2>System.Protocol // United</h2>
        </div>

        <!-- The Photo -->
        <div class="image-outer-frame">
            <div class="image-inner">
                <img src="{image_url}" alt="Team Night Out">
            </div>
        </div>

        <!-- Typography Overlay -->
        <div class="hero-text">
            <h1>{data.get('title', 'TEAM').split()[0] if data.get('title') else 'TEAM'}<span>{data.get('title', 'NIGHT').split()[-1] if data.get('title') else 'NIGHT'}</span></h1>
        </div>

        <div class="meta-badge">
            <div>DEPLOYMENT_PHASE</div>
            <strong>{data.get('company', 'CULTURE_SYNC')}_{data.get('date', '2024').split('-')[0] if '-' in data.get('date', '2024') else data.get('date', '2024')}</strong>
        </div>
    </div>
</body>
</html>"""
    
    # Template 17 HTML (Tech HUD Interface Frame)
    elif template_num == 17:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tech HUD Interface Frame</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@900&family=Work+Sans:wght@300;800&family=JetBrains+Mono:wght@400;700&display=swap');

        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #0A1622;
            --brand-white: #FFFFFF;
            --brand-bg: #050a0f;
            --glow-color: rgba(76, 182, 167, 0.4);
        }}

        body {{
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: var(--brand-bg);
            font-family: 'Work Sans', sans-serif;
            overflow: hidden;
        }}

        /* Large Format Canvas */
        .canvas-container {{
            position: relative;
            width: 1150px;
            height: 750px;
            background: var(--brand-navy);
            box-shadow: 0 0 100px rgba(0,0,0,0.8);
            overflow: hidden;
            border: 1px solid rgba(76, 182, 167, 0.15);
        }}

        /* Scanline Overlay Effect */
        .canvas-container::before {{
            content: " ";
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.1) 50%), linear-gradient(90deg, rgba(255, 0, 0, 0.02), rgba(0, 255, 0, 0.01), rgba(0, 0, 255, 0.02));
            background-size: 100% 4px, 3px 100%;
            pointer-events: none;
            z-index: 50;
        }}

        /* Main Image Container: HUD Focus */
        .hud-focus-area {{
            position: absolute;
            top: 50px;
            left: 50px;
            right: 320px; /* Leave room for sidebar */
            bottom: 50px;
            z-index: 10;
        }}

        .photo-wrap {{
            width: 100%;
            height: 100%;
            background: var(--brand-white);
            padding: 4px;
            box-sizing: border-box;
            position: relative;
        }}

        .photo-wrap img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }}

        /* HUD Brackets */
        .bracket {{
            position: absolute;
            width: 60px;
            height: 60px;
            border: 2px solid var(--brand-teal);
            z-index: 20;
        }}
        .tl {{ top: -10px; left: -10px; border-right: 0; border-bottom: 0; }}
        .tr {{ top: -10px; right: -10px; border-left: 0; border-bottom: 0; }}
        .bl {{ bottom: -10px; left: -10px; border-right: 0; border-top: 0; }}
        .br {{ bottom: -10px; right: -10px; border-left: 0; border-top: 0; }}

        /* Tech Sidebar */
        .tech-sidebar {{
            position: absolute;
            top: 50px;
            right: 50px;
            width: 240px;
            bottom: 50px;
            background: rgba(255, 255, 255, 0.03);
            border-left: 1px solid rgba(76, 182, 167, 0.3);
            padding: 30px 20px;
            z-index: 10;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }}

        .logo-area {{
            background: var(--brand-white);
            padding: 15px;
            margin-bottom: 40px;
        }}

        .logo-area img {{
            width: 100%;
            height: auto;
        }}

        .data-points {{
            font-family: 'JetBrains Mono', monospace;
            color: var(--brand-teal);
            font-size: 10px;
            line-height: 2;
        }}

        .data-points b {{
            color: var(--brand-white);
            display: block;
            margin-top: 10px;
            font-size: 12px;
        }}

        /* Hero Typography - Overlapping the frame edge */
        .hero-title {{
            position: absolute;
            bottom: 40px;
            left: 30px;
            z-index: 30;
        }}

        .hero-title h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 110px;
            line-height: 0.8;
            margin: 0;
            color: var(--brand-white);
            text-transform: uppercase;
            letter-spacing: -5px;
            text-shadow: 0 0 30px rgba(0,0,0,0.8);
        }}

        .hero-title h1 span {{
            color: var(--brand-teal);
            display: block;
            padding-left: 60px;
            text-shadow: 0 0 20px var(--glow-color);
        }}

        /* Abstract UI Elements */
        .center-crosshair {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 40px;
            height: 40px;
            z-index: 15;
            opacity: 0.5;
        }}
        .center-crosshair::before, .center-crosshair::after {{
            content: "";
            position: absolute;
            background: var(--brand-teal);
        }}
        .center-crosshair::before {{ width: 100%; height: 1px; top: 50%; left: 0; }}
        .center-crosshair::after {{ height: 100%; width: 1px; left: 50%; top: 0; }}

        .vertical-id {{
            position: absolute;
            right: 15px;
            top: 50%;
            transform: translateY(-50%) rotate(90deg);
            font-family: 'JetBrains Mono', monospace;
            font-size: 9px;
            letter-spacing: 8px;
            color: var(--brand-white);
            opacity: 0.2;
        }}
    </style>
</head>
<body>
    <div class="canvas-container">
        <!-- Structural Labels -->
        <div class="vertical-id">UNIT.04 // CORE_ASSET</div>

        <!-- HUD Photo Frame -->
        <div class="hud-focus-area">
            <div class="bracket tl"></div>
            <div class="bracket tr"></div>
            <div class="bracket bl"></div>
            <div class="bracket br"></div>
            <div class="center-crosshair"></div>
            
            <div class="photo-wrap">
                <img src="{image_url}" alt="Team Night Out">
            </div>
        </div>

        <!-- Typography -->
        <div class="hero-title">
            <h1>{data.get('title', 'TEAM').split()[0] if data.get('title') else 'TEAM'}<span>{data.get('title', 'NIGHT').split()[-1] if data.get('title') else 'NIGHT'}</span></h1>
        </div>

        <!-- Tech Sidebar Panel -->
        <div class="tech-sidebar">
            <div class="top-meta">
                <div class="logo-area">
                    <img src="{logo_url}" alt="Logo">
                </div>
                <div class="data-points">
                    <b>ENTITY_STATUS</b>
                    UNITED_GROWTH_{data.get('date', '2024').split('-')[0] if '-' in data.get('date', '2024') else data.get('date', '2024')}
                    <b>OBJECTIVE_ID</b>
                    {data.get('company', 'CULTURE_SYNC_INIT')}
                    <b>NODE_LOCATION</b>
                    EXT_EVENT_04
                </div>
            </div>

            <div class="bottom-meta">
                <div class="data-points">
                    [ // AUTHENTICATED ]<br>
                    SESSION.TOKEN: 8x92-TY<br>
                    VER: 2.5.0_STABLE
                </div>
            </div>
        </div>
    </div>
</body>
</html>"""
    
    # Template 18 HTML (Creative Brand Frame)
    elif template_num == 18:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Creative Brand Frame</title>
    <style>
        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #1A2B3C;
            --brand-white: #FFFFFF;
        }}

        body {{
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: #f0f2f5;
            margin: 0;
            font-family: 'Montserrat', sans-serif;
        }}

        /* The Main Canvas */
        .canvas {{
            position: relative;
            width: 1000px;
            height: 700px;
            background-color: var(--brand-white);
            overflow: hidden;
            box-shadow: 0 50px 100px rgba(0,0,0,0.1);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }}

        /* Large Navy Curve background */
        .canvas::before {{
            content: "";
            position: absolute;
            top: -10%;
            left: -10%;
            width: 120%;
            height: 50%;
            background-color: var(--brand-navy);
            border-radius: 0 0 50% 50%;
            z-index: 1;
        }}

        /* Floating Teal Circle Accent */
        .canvas::after {{
            content: "";
            position: absolute;
            bottom: -50px;
            right: -50px;
            width: 300px;
            height: 300px;
            background-color: var(--brand-teal);
            border-radius: 50%;
            opacity: 0.1;
            z-index: 1;
        }}

        /* Image Wrapper with Offset Borders */
        .photo-container {{
            position: relative;
            width: 85%;
            height: 70%;
            z-index: 10;
            border-radius: 12px;
            box-shadow: 0 25px 50px rgba(0,0,0,0.2);
        }}

        /* The Teal Offset Border */
        .photo-container::before {{
            content: "";
            position: absolute;
            top: 20px;
            left: 20px;
            right: -20px;
            bottom: -20px;
            border: 4px solid var(--brand-teal);
            border-radius: 12px;
            z-index: -1;
        }}

        .photo-container img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            border-radius: 12px;
            display: block;
        }}

        /* Bottom Branding Section */
        .footer-branding {{
            position: relative;
            width: 85%;
            margin-top: 50px;
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            z-index: 10;
        }}

        .logo-area {{
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            gap: 15px;
        }}

        .logo-area img {{
            height: 75px;
            width: auto;
        }}

        .text-area {{
            text-align: right;
        }}

        .text-area h1 {{
            margin: 0;
            color: var(--brand-navy);
            font-size: 36px;
            font-weight: 900;
            letter-spacing: -1px;
            line-height: 1;
        }}

        .text-area p {{
            margin: 5px 0 0;
            color: var(--brand-teal);
            font-size: 16px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 3px;
        }}

        /* Decorative "Logo Shape" in corner */
        .shape-accent {{
            position: absolute;
            top: 40px;
            left: 40px;
            width: 80px;
            height: 80px;
            background: linear-gradient(45deg, var(--brand-teal), transparent);
            border-radius: 40% 60% 70% 30% / 40% 50% 60% 70%;
            z-index: 2;
            animation: morph 8s ease-in-out infinite;
        }}

        @keyframes morph {{
            0% {{ border-radius: 40% 60% 70% 30% / 40% 50% 60% 70%; }}
            50% {{ border-radius: 70% 30% 30% 70% / 70% 30% 70% 30%; }}
            100% {{ border-radius: 40% 60% 70% 30% / 40% 50% 60% 70%; }}
        }}
    </style>
</head>
<body>
    <div class="canvas">
        <div class="shape-accent"></div>

        <div class="photo-container">
            <img src="{image_url}" alt="Team Night Out">
        </div>

        <div class="footer-branding">
            <div class="logo-area">
                <img src="{logo_url}" alt="Company Logo">
            </div>
            
            <div class="text-area">
                <h1>{data.get('title', 'Our Team Night Out')}</h1>
                <p>{data.get('company', 'Together We Lead')}</p>
            </div>
        </div>
    </div>
</body>
</html>"""
    
    # Template 19 HTML (Wide Cinema Brand Frame)
    elif template_num == 19:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Wide Cinema Brand Frame</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@900&family=Work+Sans:wght@300;800&display=swap');

        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #1A2B3C;
            --brand-white: #FFFFFF;
            --brand-bg: #f1f5f9;
        }}

        body {{
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: var(--brand-bg);
            font-family: 'Work Sans', sans-serif;
            overflow: hidden;
        }}

        /* Large Format Canvas */
        .canvas-container {{
            position: relative;
            width: 1100px;
            height: 700px;
            background: var(--brand-white);
            box-shadow: 0 50px 100px rgba(0,0,0,0.12);
            padding: 20px;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
        }}

        /* Top Bar Branding */
        .top-branding {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 20px 20px;
            border-bottom: 1px solid #eee;
        }}

        .logo-area img {{
            height: 50px;
            width: auto;
        }}

        .event-tag {{
            font-size: 12px;
            font-weight: 800;
            letter-spacing: 3px;
            color: var(--brand-teal);
            text-transform: uppercase;
        }}

        /* Massive Image Area */
        .photo-main {{
            position: relative;
            flex-grow: 1;
            margin-top: 20px;
            background: var(--brand-navy);
            border-radius: 4px;
            overflow: hidden;
        }}

        .photo-main img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }}

        /* Bottom Floating Identity */
        .identity-overlay {{
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            padding: 60px 40px 40px;
            background: linear-gradient(to top, rgba(26, 43, 60, 0.95) 0%, rgba(26, 43, 60, 0.6) 60%, transparent 100%);
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            color: var(--brand-white);
        }}

        .title-group h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 72px;
            margin: 0;
            line-height: 0.85;
            letter-spacing: -2px;
        }}

        .title-group h1 span {{
            color: var(--brand-teal);
        }}

        .subtitle {{
            margin-top: 15px;
            font-size: 14px;
            letter-spacing: 5px;
            text-transform: uppercase;
            opacity: 0.8;
            border-left: 3px solid var(--brand-teal);
            padding-left: 15px;
        }}

        /* Geometric Accents for Static Punch */
        .teal-accent-box {{
            position: absolute;
            top: 40px;
            right: 40px;
            width: 60px;
            height: 60px;
            border-top: 4px solid var(--brand-teal);
            border-right: 4px solid var(--brand-teal);
            z-index: 20;
        }}

        .navy-accent-bar {{
            position: absolute;
            left: 0;
            top: 50%;
            transform: translateY(-50%);
            width: 8px;
            height: 120px;
            background: var(--brand-teal);
            border-radius: 0 4px 4px 0;
        }}

        .year-vertical {{
            font-family: 'Outfit', sans-serif;
            font-size: 40px;
            font-weight: 900;
            color: var(--brand-white);
            opacity: 0.3;
            writing-mode: vertical-rl;
        }}
    </style>
</head>
<body>
    <div class="canvas-container">
        <!-- Minimal Top Navigation -->
        <div class="top-branding">
            <div class="logo-area">
                <img src="{logo_url}" alt="Company Logo">
            </div>
            <div class="event-tag">{data.get('company', 'COMMUNITY & CULTURE')}</div>
        </div>

        <!-- The Photo (Maximizing the Area) -->
        <div class="photo-main">
            <img src="{image_url}" alt="Team Night Out">
            
            <div class="teal-accent-box"></div>
            <div class="navy-accent-bar"></div>

            <!-- Identity Bar Overlaid on Photo -->
            <div class="identity-overlay">
                <div class="title-group">
                    <h1>{data.get('title', 'TEAM NIGHT').split()[0] if data.get('title') else 'TEAM'}<span>{data.get('title', 'NIGHT OUT').split()[-1] if data.get('title') else 'NIGHT'}</span></h1>
                    <p class="subtitle">{data.get('name', 'United by Purpose')} • {data.get('date', '2024').split('-')[0] if '-' in data.get('date', '2024') else data.get('date', '2024')}</p>
                </div>
                
                <div class="year-vertical">
                    MEMORIES
                </div>
            </div>
        </div>
    </div>
</body>
</html>"""
    
    # Template 20 HTML (Editorial Brand Experience - Template 5 from your request)
    elif template_num == 20:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Editorial Brand Experience</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;700;900&family=Syne:wght@800&display=swap');

        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #1A2B3C;
            --brand-white: #FFFFFF;
            --brand-bg: #e2e8f0;
        }}

        body {{
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: var(--brand-bg);
            font-family: 'Outfit', sans-serif;
            overflow-x: hidden;
        }}

        /* Abstract Background Decor */
        .deco-container {{
            position: absolute;
            width: 100%;
            height: 100%;
            z-index: -1;
            overflow: hidden;
        }}

        .deco-circle {{
            position: absolute;
            border: 2px solid var(--brand-teal);
            border-radius: 50%;
            opacity: 0.2;
        }}

        /* Creative Canvas */
        .creative-wrapper {{
            position: relative;
            width: 95%;
            max-width: 1100px;
            background: var(--brand-white);
            padding: 60px 40px;
            box-sizing: border-box;
            box-shadow: 0 60px 120px rgba(26, 43, 60, 0.1);
            display: grid;
            grid-template-columns: 1fr;
            gap: 0;
        }}

        /* Large Accent Lettering Background */
        .bg-text {{
            position: absolute;
            top: 10px;
            right: -20px;
            font-family: 'Syne', sans-serif;
            font-size: 200px;
            line-height: 0.8;
            color: var(--brand-navy);
            opacity: 0.03;
            pointer-events: none;
            z-index: 1;
        }}

        /* Main Photo Container - Floating & Layered */
        .main-frame {{
            position: relative;
            z-index: 5;
            margin-bottom: -40px; /* Overlaps the footer for depth */
        }}

        .photo-box {{
            position: relative;
            width: 100%;
            background: var(--brand-navy);
            padding: 10px;
            box-sizing: border-box;
            box-shadow: 20px 20px 0px var(--brand-teal);
            transition: all 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }}

        .photo-box:hover {{
            box-shadow: 10px 10px 0px var(--brand-teal);
            transform: translate(5px, 5px);
        }}

        .photo-box img {{
            width: 100%;
            height: auto;
            display: block;
            object-fit: contain;
        }}

        /* Branding Overlay Section */
        .brand-footer {{
            position: relative;
            background: var(--brand-white);
            padding: 60px 30px 20px;
            z-index: 10;
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            border-left: 15px solid var(--brand-teal);
        }}

        .content-group {{
            max-width: 600px;
        }}

        .content-group h2 {{
            font-family: 'Syne', sans-serif;
            font-size: 64px;
            margin: 0;
            color: var(--brand-navy);
            text-transform: uppercase;
            line-height: 0.9;
        }}

        .content-group h2 span {{
            display: block;
            color: var(--brand-teal);
        }}

        .meta-info {{
            margin-top: 15px;
            font-size: 16px;
            color: #64748b;
            display: flex;
            gap: 20px;
            align-items: center;
        }}

        .meta-info::before {{
            content: "";
            width: 40px;
            height: 2px;
            background: var(--brand-teal);
        }}

        /* Logo Integrated as a Floating Stamp */
        .logo-stamp {{
            position: absolute;
            top: -50px;
            right: 40px;
            background: var(--brand-white);
            width: 120px;
            height: 120px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            padding: 20px;
            box-sizing: border-box;
            z-index: 15;
            border: 2px dashed var(--brand-teal);
        }}

        .logo-stamp img {{
            width: 100%;
            height: auto;
        }}

        /* Small Geometric Decor dots */
        .dots {{
            position: absolute;
            top: 30px;
            left: 30px;
            display: grid;
            grid-template-columns: repeat(3, 10px);
            gap: 10px;
        }}

        .dot {{
            width: 10px;
            height: 10px;
            background: var(--brand-teal);
            border-radius: 50%;
        }}
    </style>
</head>
<body>
    <div class="deco-container">
        <div class="deco-circle" style="width: 400px; height: 400px; top: -100px; left: -100px;"></div>
        <div class="deco-circle" style="width: 600px; height: 600px; bottom: -200px; right: -200px;"></div>
    </div>

    <div class="creative-wrapper">
        <div class="bg-text">TEAM</div>
        
        <div class="dots">
            <div class="dot"></div><div class="dot"></div><div class="dot"></div>
            <div class="dot"></div><div class="dot"></div><div class="dot"></div>
        </div>

        <!-- Floating Image Section -->
        <div class="main-frame">
            <div class="photo-box">
                <img src="{image_url}" alt="Company Team">
            </div>
        </div>

        <!-- Creative Footer Section -->
        <div class="brand-footer">
            <div class="logo-stamp">
                <img src="{logo_url}" alt="Brand Logo">
            </div>

            <div class="content-group">
                <h2>OUR {data.get('title', 'TEAM NIGHT').split()[0] if data.get('title') else 'TEAM'} <span>{data.get('title', 'NIGHT OUT').split()[-1] if data.get('title') else 'NIGHT'}</span></h2>
                <div class="meta-info">{data.get('company', 'ESTABLISHED')} {data.get('date', '2024').split('-')[0] if '-' in data.get('date', '2024') else data.get('date', '2024')} • {data.get('name', 'CORPORATE CULTURE')}</div>
            </div>

            <div style="font-family: 'Syne', sans-serif; font-size: 48px; color: var(--brand-navy); opacity: 0.2;">
                01
            </div>
        </div>
    </div>
</body>
</html>"""
    # Simple template for all cases (you should use your actual 20 templates here)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Template {template_num} - {content['title']}</title>
    <style>
        :root {{
            --brand-teal: #4CB6A7;
            --brand-navy: #1A2B3C;
            --brand-white: #FFFFFF;
            --brand-bg: #f8fafc;
        }}
        
        body {{
            margin: 0;
            padding: 40px;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background: var(--brand-bg);
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }}
        
        .template-frame {{
            width: 1000px;
            background: white;
            border-radius: 20px;
            overflow: hidden;
            box-shadow: 0 30px 60px rgba(0,0,0,0.15);
            position: relative;
        }}
        
        .template-header {{
            background: linear-gradient(135deg, var(--brand-navy) 0%, #0f172a 100%);
            color: white;
            padding: 40px;
            position: relative;
            overflow: hidden;
        }}
        
        .template-header::before {{
            content: "";
            position: absolute;
            top: -50px;
            right: -50px;
            width: 200px;
            height: 200px;
            background: var(--brand-teal);
            opacity: 0.2;
            border-radius: 50%;
        }}
        
        .template-badge {{
            display: inline-block;
            background: var(--brand-teal);
            color: var(--brand-navy);
            padding: 8px 20px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        
        .template-title {{
            font-size: 3.5rem;
            font-weight: 900;
            line-height: 1;
            margin-bottom: 10px;
        }}
        
        .template-subtitle {{
            font-size: 1.2rem;
            opacity: 0.9;
            margin-bottom: 30px;
        }}
        
        .image-container {{
            width: 100%;
            height: 500px;
            background: #e2e8f0;
            overflow: hidden;
            position: relative;
        }}
        
        .image-container img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
        }}
        
        .logo-container {{
            position: absolute;
            bottom: 30px;
            right: 30px;
            background: white;
            padding: 20px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }}
        
        .logo-container img {{
            width: 100px;
            height: auto;
        }}
        
        .content-section {{
            padding: 40px;
        }}
        
        .content-text {{
            font-size: 1.1rem;
            line-height: 1.6;
            color: #334155;
            margin-bottom: 25px;
            padding: 20px;
            background: #f8fafc;
            border-radius: 10px;
            border-left: 4px solid var(--brand-teal);
        }}
        
        .metadata {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-top: 30px;
            border-top: 2px solid #e2e8f0;
        }}
        
        .hashtags {{
            color: var(--brand-teal);
            font-weight: bold;
            font-size: 1rem;
        }}
        
        .cta-button {{
            background: var(--brand-teal);
            color: white;
            padding: 12px 30px;
            border-radius: 8px;
            text-decoration: none;
            font-weight: bold;
            display: inline-block;
        }}
        
        .footer {{
            background: var(--brand-navy);
            color: white;
            padding: 25px 40px;
            text-align: center;
            font-size: 0.9rem;
            opacity: 0.9;
        }}
        
        .template-number {{
            position: absolute;
            top: 30px;
            right: 30px;
            font-size: 2rem;
            font-weight: 900;
            color: rgba(255,255,255,0.1);
        }}
    </style>
</head>
<body>
    <div class="template-frame">
        <div class="template-number">#{template_num}</div>
        
        <div class="template-header">
            <div class="template-badge">Template {template_num}</div>
            <h1 class="template-title">{content['title']}</h1>
            <div class="template-subtitle">
                {content['company']} • {content['date']} • {content['name']}
            </div>
        </div>
        
        <div class="image-container">
            <img src="{image_url}" alt="Event Image">
            <div class="logo-container">
                <img src="{logo_url}" alt="Company Logo">
            </div>
        </div>
        
        <div class="content-section">
            {f'<div class="content-text">{content["custom_text1"]}</div>' if content.get('custom_text1') else ''}
            {f'<div class="content-text">{content["custom_text2"]}</div>' if content.get('custom_text2') else ''}
            
            <div class="metadata">
                <div class="hashtags">
                    {content['hashtags'] if content.get('hashtags') else '#Team #Event #Success'}
                </div>
                <div class="cta-button">
                    {content['cta'] if content.get('cta') else 'Share this moment!'}
                </div>
            </div>
        </div>
        
        <div class="footer">
            Smart Template Generator • Created with AI Assistance • Template {template_num}
        </div>
    </div>
</body>
</html>"""
    

# =============================================
# GENERATION FUNCTIONS
# =============================================

def generate_jpg_in_memory(template_num, data, edited_content, image_data, logo_data):
    """Generate JPG in-memory"""
    return ImageGenerator.generate_template_image(template_num, data, edited_content, image_data, logo_data)

# =============================================
# FLASK ROUTES
# =============================================

@app.route("/")
def index():
    """Home page with form"""
    return render_template("form.html")

@app.route("/", methods=["POST"])
def process_form():
    """Process form submission with IMPROVED template selection"""
    if request.method == "POST":
        print("📝 Processing form submission...")
       
        session_id = str(uuid.uuid4())
        session.clear()
        session['session_id'] = session_id
       
        image_file = request.files.get("image")
        logo_file = request.files.get("logo")
       
        if not image_file:
            return render_template("form.html", error="Please upload an image")
       
        image_data = image_file.read()
        logo_data = logo_file.read() if logo_file else None
       
        form_data = {
            "title": request.form.get("title", "") or "Team Bigibyte Event",
            "company": request.form.get("company", "") or "Bigibyte",
            "date": request.form.get("date", "") or "2026-01-28",
            "name": request.form.get("name", "") or "Md Firoz Islam",
        }
       
        # AI Analysis
        print("🤖 Running AI image analysis...")
        ai_analysis = AIAssistant.analyze_image(image_data)
        user_input_text = f"{form_data['title']} {form_data['company']}"
        ai_generated_content = AIAssistant.generate_content_from_prompt(user_input_text, ai_analysis)
       
        # IMPROVED: Enhanced template selection with AI integration
        print("🎯 Analyzing user input and selecting best templates...")
        analyzer = SmartTemplateAnalyzer()
        user_analysis = analyzer.analyze_input(
            form_data, 
            ai_analysis.get('orientation', 'horizontal'),
            ai_image_analysis=ai_analysis  # Pass AI analysis for better matching
        )
        best_template_nums = analyzer.select_best_templates(
            user_analysis, 
            ai_image_analysis=ai_analysis  # Pass AI analysis for scoring boost
        )
       
        TEMP_STORAGE[session_id] = {
            'image_data': image_data,
            'logo_data': logo_data,
            'form_data': form_data,
            'user_analysis': user_analysis,
            'selected_templates': best_template_nums,
            'ai_analysis': ai_analysis,
            'ai_generated_content': ai_generated_content
        }
       
        session['form_data'] = form_data
        session['selected_templates'] = best_template_nums
       
        print(f"✅ Form processed: {session_id}")
        print(f"🎨 Selected Templates: {best_template_nums}")
       
        return redirect(url_for('edit_content', session_id=session_id))
   
    return redirect(url_for('index'))

@app.route("/edit-content/<session_id>")
def edit_content(session_id):
    """Page to edit text content"""
    if 'session_id' not in session or session['session_id'] != session_id:
        return redirect(url_for('index'))
   
    if session_id not in TEMP_STORAGE:
        return redirect(url_for('index'))
   
    temp_data = TEMP_STORAGE[session_id]
   
    return render_template("edit_content.html",
                         session_id=session_id,
                         form_data=temp_data['form_data'],
                         ai_analysis=temp_data['ai_analysis'],
                         ai_content=temp_data['ai_generated_content'],
                         template_count=len(temp_data['selected_templates']))

@app.route("/save-content/<session_id>", methods=["POST"])
def save_content(session_id):
    """Save edited content"""
    if 'session_id' not in session or session['session_id'] != session_id:
        return jsonify({"error": "Invalid session"}), 400
   
    if session_id not in TEMP_STORAGE:
        return jsonify({"error": "Session data not found"}), 400
   
    edited_content = {
        "title": request.form.get("title", ""),
        "company": request.form.get("company", ""),
        "date": request.form.get("date", ""),
        "name": request.form.get("name", ""),
    }
   
    TEMP_STORAGE[session_id]['form_data'].update(edited_content)
    TEMP_STORAGE[session_id]['edited_content'] = edited_content
    session['form_data'] = TEMP_STORAGE[session_id]['form_data']
    session['edited_content'] = edited_content
   
    return jsonify({"success": True, "redirect": url_for('generate_templates', session_id=session_id)})

@app.route("/generate-templates/<session_id>")
def generate_templates(session_id):
    """Show download links for templates"""
    if 'session_id' not in session or session['session_id'] != session_id:
        return redirect(url_for('index'))
   
    if session_id not in TEMP_STORAGE:
        return redirect(url_for('index'))
   
    temp_data = TEMP_STORAGE[session_id]
    best_template_nums = temp_data['selected_templates']
   
    all_files = []
    for template_num in best_template_nums:
        template_info = SmartTemplateAnalyzer.TEMPLATE_CHARACTERISTICS.get(template_num, {})
        all_files.append({
            "filename": f"template_{template_num}.jpg",
            "template_num": template_num,
            "template_name": template_info.get("name", f"Template {template_num}"),
            "template_style": template_info.get("style", ""),
            "template_mood": template_info.get("mood", ""),
            "download_url": f"/download-template/{session_id}/{template_num}",
            "edit_url": f"/edit-template-text/{session_id}/{template_num}",
        })
   
    return render_template("download.html",
                         files_data=all_files,
                         user_analysis=temp_data['user_analysis'],
                         selected_templates=best_template_nums,
                         template_count=len(all_files),
                         session_id=session_id)

@app.route("/download-template/<session_id>/<int:template_num>")
def download_template(session_id, template_num):
    """Download a single template"""
    if 'session_id' not in session or session['session_id'] != session_id:
        return "Invalid session", 400
   
    if session_id not in TEMP_STORAGE:
        return "Session data not found", 400
   
    temp_data = TEMP_STORAGE[session_id]
    edited_content = temp_data.get('edited_content', temp_data['form_data'])
    image_data = temp_data['image_data']
    logo_data = temp_data['logo_data']
    form_data = temp_data['form_data']
   
    print(f"📥 Generating template {template_num}...")
   
    try:
        image_bytes = generate_jpg_in_memory(template_num, form_data, edited_content, image_data, logo_data)
       
        if not image_bytes:
            return "Generation failed", 500
       
        return send_file(
            BytesIO(image_bytes),
            mimetype='image/jpeg',
            as_attachment=True,
            download_name=f'template_{template_num}.jpg'
        )
       
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return f"Error: {str(e)}", 500

@app.route("/generate-preview/<session_id>/<int:template_num>")
def generate_preview(session_id, template_num):
    """Generate preview for a template"""
    if session_id not in TEMP_STORAGE:
        return jsonify({"success": False, "error": "Session not found"})
   
    temp_data = TEMP_STORAGE[session_id]
    cache_key = f"{session_id}_{template_num}_{hashlib.md5(temp_data['image_data']).hexdigest()[:16]}"
   
    if cache_key in PREVIEW_CACHE:
        print(f"[CACHE] Using cached preview for template {template_num}")
        cached_data = PREVIEW_CACHE[cache_key]
        return jsonify({
            "success": True,
            "preview_b64": cached_data['thumbnail'],
            "fullsize_b64": cached_data['fullsize'],
            "template_num": template_num,
            "cached": True
        })
   
    try:
        edited_content = temp_data.get('edited_content', temp_data['form_data'])
        image_data = temp_data['image_data']
        logo_data = temp_data.get('logo_data')
        form_data = temp_data['form_data']
       
        print(f"🔄 Generating preview for template {template_num}...")
       
        image_bytes = generate_jpg_in_memory(template_num, form_data, edited_content, image_data, logo_data)
       
        if image_bytes:
            fullsize_b64 = base64.b64encode(image_bytes).decode('utf-8')
           
            try:
                from PIL import Image
                img = Image.open(BytesIO(image_bytes))
                img.thumbnail((400, 300), Image.Resampling.LANCZOS)
               
                thumb_byte_arr = BytesIO()
                img.save(thumb_byte_arr, format='JPEG', quality=80, optimize=True)
                thumbnail_b64 = base64.b64encode(thumb_byte_arr.getvalue()).decode('utf-8')
            except:
                thumbnail_b64 = fullsize_b64
           
            PREVIEW_CACHE[cache_key] = {
                'thumbnail': thumbnail_b64,
                'fullsize': fullsize_b64,
                'dimensions': "1200x800"
            }
           
            if len(PREVIEW_CACHE) > 20:
                oldest_key = list(PREVIEW_CACHE.keys())[0]
                del PREVIEW_CACHE[oldest_key]
           
            print(f"✅ Generated preview for template {template_num}")
           
            return jsonify({
                "success": True,
                "preview_b64": thumbnail_b64,
                "fullsize_b64": fullsize_b64,
                "template_num": template_num,
                "cached": False
            })
           
    except Exception as e:
        print(f"❌ Error generating preview: {e}")
        import traceback
        traceback.print_exc()
   
    return jsonify({"success": False, "error": "Failed to generate preview"})

@app.route("/edit-template-text/<session_id>/<int:template_num>")
def edit_template_text(session_id, template_num):
    """Edit text for specific template"""
    if 'session_id' not in session or session['session_id'] != session_id:
        return redirect(url_for('index'))
   
    if session_id not in TEMP_STORAGE:
        return redirect(url_for('index'))
   
    temp_data = TEMP_STORAGE[session_id]
   
    if template_num not in temp_data['selected_templates']:
        return redirect(url_for('generate_templates', session_id=session_id))
   
    existing_content = TextContentManager.load_text_content(session_id, template_num)
    if not existing_content:
        existing_content = temp_data.get('edited_content', temp_data['form_data'])
   
    template_info = SmartTemplateAnalyzer.TEMPLATE_CHARACTERISTICS.get(template_num, {})
   
    return render_template("edit_single_template.html",
                         session_id=session_id,
                         template_num=template_num,
                         template_info=template_info,
                         content=existing_content,
                         ai_content=temp_data['ai_generated_content'])

@app.route("/update-template-text/<session_id>/<int:template_num>", methods=["POST"])
def update_template_text(session_id, template_num):
    """Update text for specific template"""
    if 'session_id' not in session or session['session_id'] != session_id:
        return jsonify({"error": "Invalid session"}), 400
   
    if session_id not in TEMP_STORAGE:
        return jsonify({"error": "Session data not found"}), 400
   
    updated_content = {
        "title": request.form.get("title", ""),
        "company": request.form.get("company", ""),
        "date": request.form.get("date", ""),
        "name": request.form.get("name", ""),
    }
   
    TextContentManager.save_text_content(session_id, template_num, updated_content)
    TEMP_STORAGE[session_id]['form_data'].update(updated_content)
   
    return jsonify({
        "success": True,
        "message": "Template updated successfully",
        "template_num": template_num,
        "download_url": f"/download-template/{session_id}/{template_num}"
    })

@app.route("/clear-session/<session_id>")
def clear_session(session_id):
    """Clear session data"""
    if 'session_id' in session and session['session_id'] == session_id:
        cleanup_session_data(session_id)
        TextContentManager.delete_text_content(session_id)
        session.clear()
   
    return redirect(url_for('index'))

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files"""
    root_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(os.path.join(root_dir, 'static'), filename)

@app.route("/health")
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

if __name__ == "__main__":
    print("[*] Starting Smart Template Generator...")
    print("[*] Server running on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
