from flask import Flask
from threading import Thread
import discord
from discord import Option
from discord.ext import commands
from discord.ui import Button, View
import google.generativeai as genai
import os
import asyncio
import json
import random
from datetime import datetime, timedelta

# =============================
# KEEP ALIVE SERVER
# =============================
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    Thread(target=run).start()

# =============================
# BOT CONFIG
# =============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Data storage
channel_history = {}
user_quiz_scores = {}
user_flashcards = {}
user_study_stats = {}
active_pomodoro = {}
flashcard_reviews = {}

# =============================
# HELPER FUNCTIONS
# =============================
async def async_generate(prompt):
    """Run Gemini API asynchronously."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: model.generate_content(prompt))

def make_embed(title, text, color=0x1abc9c):
    """Return a Discord embed for nicer formatting."""
    embed = discord.Embed(title=title, description=text, color=color)
    return embed

def update_quiz_stats(user_id, topic, correct):
    if user_id not in user_quiz_scores:
        user_quiz_scores[user_id] = {"correct": 0, "total": 0, "topics": {}}
    if correct:
        user_quiz_scores[user_id]["correct"] += 1
        user_quiz_scores[user_id]["topics"][topic] = user_quiz_scores[user_id]["topics"].get(topic, 0) + 1
    user_quiz_scores[user_id]["total"] += 1
    
    if user_id not in user_study_stats:
        user_study_stats[user_id] = {"quizzes": 0, "practice": 0, "pomodoros": 0}
    user_study_stats[user_id]["quizzes"] += 1

class QuizView(View):
    def __init__(self, correct_answer, options, user_id, topic):
        super().__init__(timeout=60)
        self.correct_answer = correct_answer
        self.user_id = user_id
        self.topic = topic
        self.answered = False
        
        for i, option in enumerate(options):
            button = Button(
                label=option,
                style=discord.ButtonStyle.primary,
                custom_id=f"quiz_{i}"
            )
            button.callback = self.button_callback
            self.add_item(button)
    
    async def button_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This quiz is not for you!", ephemeral=True)
            return
        
        if self.answered:
            await interaction.response.send_message("You already answered!", ephemeral=True)
            return
        
        self.answered = True
        selected = interaction.data["custom_id"]
        selected_index = int(selected.split("_")[1])
        selected_answer = self.children[selected_index].label
        
        correct = selected_answer == self.correct_answer
        update_quiz_stats(self.user_id, self.topic, correct)
        
        if correct:
            embed = make_embed("✅ Correct!", f"Great job! The answer is: **{self.correct_answer}**", color=0x2ecc71)
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            embed = make_embed("❌ Incorrect", f"The correct answer is: **{self.correct_answer}**", color=0xe74c3c)
            await interaction.response.edit_message(embed=embed, view=None)

class TrueFalseView(View):
    def __init__(self, correct_answer, user_id, topic):
        super().__init__(timeout=60)
        self.correct_answer = correct_answer.lower()
        self.user_id = user_id
        self.topic = topic
        self.answered = False
    
    @discord.ui.button(label="✅ True", style=discord.ButtonStyle.success, custom_id="true")
    async def true_button(self, button: Button, interaction: discord.Interaction):
        await self.process_answer(interaction, "true")
    
    @discord.ui.button(label="❌ False", style=discord.ButtonStyle.danger, custom_id="false")
    async def false_button(self, button: Button, interaction: discord.Interaction):
        await self.process_answer(interaction, "false")
    
    async def process_answer(self, interaction: discord.Interaction, answer: str):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This quiz is not for you!", ephemeral=True)
            return
        
        if self.answered:
            await interaction.response.send_message("You already answered!", ephemeral=True)
            return
        
        self.answered = True
        correct = answer == self.correct_answer
        update_quiz_stats(self.user_id, self.topic, correct)
        
        if correct:
            embed = make_embed("✅ Correct!", f"Yes! The answer is **{self.correct_answer.capitalize()}**", color=0x2ecc71)
        else:
            embed = make_embed("❌ Incorrect", f"The correct answer is **{self.correct_answer.capitalize()}**", color=0xe74c3c)
        
        await interaction.response.edit_message(embed=embed, view=None)

class FlashcardView(View):
    def __init__(self, question, answer, user_id, card_data=None, is_review=False):
        super().__init__(timeout=120)
        self.question = question
        self.answer = answer
        self.user_id = user_id
        self.revealed = False
        self.card_data = card_data
        self.is_review = is_review
    
    @discord.ui.button(label="Show Answer", style=discord.ButtonStyle.primary)
    async def show_answer(self, button: Button, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This flashcard is not for you!", ephemeral=True)
            return
        
        if not self.revealed:
            self.revealed = True
            embed = make_embed("💡 Answer", self.answer, color=0x9b59b6)
            
            if self.is_review and self.card_data:
                embed.description += "\n\n**How well did you know this?**"
                button.disabled = True
                
                async def easy_callback(inter):
                    await self.rate_card(inter, "easy")
                async def good_callback(inter):
                    await self.rate_card(inter, "good")
                async def hard_callback(inter):
                    await self.rate_card(inter, "hard")
                
                easy_btn = Button(label="✅ Easy", style=discord.ButtonStyle.success)
                easy_btn.callback = easy_callback
                
                good_btn = Button(label="👍 Good", style=discord.ButtonStyle.primary)
                good_btn.callback = good_callback
                
                hard_btn = Button(label="❌ Hard", style=discord.ButtonStyle.danger)
                hard_btn.callback = hard_callback
                
                self.add_item(easy_btn)
                self.add_item(good_btn)
                self.add_item(hard_btn)
            else:
                button.disabled = True
            
            await interaction.response.edit_message(embed=embed, view=self)
    
    async def rate_card(self, interaction: discord.Interaction, difficulty: str):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your card!", ephemeral=True)
            return
        
        if not self.card_data:
            return
        
        now = datetime.now()
        self.card_data["reviews"] += 1
        
        if difficulty == "easy":
            self.card_data["interval"] = min(self.card_data["interval"] * 2.5, 30)
            self.card_data["ease_factor"] = min(self.card_data["ease_factor"] + 0.15, 3.0)
            feedback = "Great! This card will appear in a longer interval."
        elif difficulty == "good":
            self.card_data["interval"] = min(self.card_data["interval"] * 2, 30)
            feedback = "Good! Standard interval applied."
        else:
            self.card_data["interval"] = max(1, self.card_data["interval"] * 0.5)
            self.card_data["ease_factor"] = max(self.card_data["ease_factor"] - 0.2, 1.3)
            feedback = "I'll show this card again soon."
        
        self.card_data["next_review"] = (now + timedelta(days=int(self.card_data["interval"]))).isoformat()
        
        result_embed = make_embed(
            "✅ Review Complete",
            f"{feedback}\nNext review: {int(self.card_data['interval'])} days",
            color=0x2ecc71
        )
        await interaction.response.edit_message(embed=result_embed, view=None)

class PomodoroView(View):
    def __init__(self, user_id, duration=25):
        super().__init__(timeout=duration * 60 + 10)
        self.user_id = user_id
        self.duration = duration
        self.paused = False
    
    @discord.ui.button(label="⏸️ Pause", style=discord.ButtonStyle.secondary)
    async def pause_button(self, button: Button, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This timer is not for you!", ephemeral=True)
            return
        
        self.paused = not self.paused
        button.label = "▶️ Resume" if self.paused else "⏸️ Pause"
        await interaction.response.edit_message(view=self)
    
    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger)
    async def stop_button(self, button: Button, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This timer is not for you!", ephemeral=True)
            return
        
        if self.user_id in active_pomodoro:
            del active_pomodoro[self.user_id]
        embed = make_embed("⏹️ Timer Stopped", "Your study session has been stopped.", color=0xe74c3c)
        await interaction.response.edit_message(embed=embed, view=None)

# =============================
# EVENTS
# =============================
@bot.event
async def on_ready():
    print(f"🤖 Logged in as {bot.user}")
    await bot.change_presence(activity=discord.Game("Supreme Study Bot 📚 | /help for commands"))

# =============================
# SLASH COMMANDS
# =============================
@bot.slash_command(description="Solve any study question with AI")
async def solve(ctx, question: Option(str, "Type your question here")):
    await ctx.respond("🧠 Thinking...")
    try:
        response = await async_generate(question)
        embed = make_embed("📘 Answer", response.text)
        await ctx.send_followup(embed=embed)

        # Save history
        channel_history.setdefault(ctx.channel.id, []).append((question, response.text))
        if len(channel_history[ctx.channel.id]) > 10:
            channel_history[ctx.channel.id].pop(0)

    except Exception:
        await ctx.send_followup("⚠️ Something went wrong. Please try again later.")

@bot.slash_command(description="Get a step-by-step explanation of a topic")
async def explain(ctx, topic: Option(str, "Topic you want explained")):
    await ctx.respond("🧠 Explaining...")
    try:
        prompt = f"Explain '{topic}' step by step for learning purposes."
        response = await async_generate(prompt)
        embed = make_embed("📝 Explanation", response.text, color=0xf1c40f)
        await ctx.send_followup(embed=embed)
    except Exception:
        await ctx.send_followup("⚠️ Could not generate explanation.")

@bot.slash_command(description="Get a concise definition of a term")
async def define(ctx, term: Option(str, "Term you want defined")):
    await ctx.respond("🧠 Searching definition...")
    try:
        prompt = f"Define '{term}' concisely."
        response = await async_generate(prompt)
        embed = make_embed("📚 Definition", response.text, color=0x3498db)
        await ctx.send_followup(embed=embed)
    except Exception:
        await ctx.send_followup("⚠️ Could not fetch definition.")

@bot.slash_command(description="Show recent questions and answers in this channel")
async def history(ctx):
    if ctx.channel.id not in channel_history or not channel_history[ctx.channel.id]:
        await ctx.respond("📜 No history available.")
        return

    embed = discord.Embed(title="📜 Recent Q&A", color=0x95a5a6)
    for q, a in channel_history[ctx.channel.id][-5:]:
        embed.add_field(name=f"Q: {q}", value=f"A: {a}", inline=False)
    await ctx.respond(embed=embed)

@bot.slash_command(description="Generate a quiz on any topic")
async def quiz(
    ctx, 
    topic: Option(str, "Topic for the quiz"), 
    quiz_type: Option(str, "Question type", choices=["Multiple Choice", "True/False", "Fill in the Blank"]) = "Multiple Choice",
    difficulty: Option(str, "Difficulty level", choices=["Easy", "Medium", "Hard"]) = "Medium"
):
    await ctx.defer()
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if quiz_type == "Multiple Choice":
                prompt = f"""Generate a {difficulty.lower()} multiple-choice question about '{topic}'.
Format your response EXACTLY as JSON:
{{
    "question": "the question here",
    "options": ["option A", "option B", "option C", "option D"],
    "correct": "the correct option from the list"
}}"""
                
                response = await async_generate(prompt)
                text = response.text.strip().replace("```json", "").replace("```", "").strip()
                quiz_data = json.loads(text)
                
                if "question" not in quiz_data or "options" not in quiz_data or "correct" not in quiz_data:
                    raise ValueError("Invalid quiz format")
                
                embed = make_embed(
                    f"📝 Quiz: {topic} ({difficulty})",
                    quiz_data["question"],
                    color=0xe67e22
                )
                view = QuizView(quiz_data["correct"], quiz_data["options"], ctx.author.id, topic)
                await ctx.followup.send(embed=embed, view=view)
                return
                
            elif quiz_type == "True/False":
                prompt = f"""Generate a {difficulty.lower()} true/false question about '{topic}'.
Format as JSON:
{{
    "question": "the statement here",
    "correct": "true" or "false"
}}"""
                
                response = await async_generate(prompt)
                text = response.text.strip().replace("```json", "").replace("```", "").strip()
                quiz_data = json.loads(text)
                
                if "question" not in quiz_data or "correct" not in quiz_data:
                    raise ValueError("Invalid quiz format")
                
                embed = make_embed(
                    f"📝 True/False: {topic} ({difficulty})",
                    quiz_data["question"],
                    color=0xe67e22
                )
                view = TrueFalseView(quiz_data["correct"], ctx.author.id, topic)
                await ctx.followup.send(embed=embed, view=view)
                return
                
            else:
                prompt = f"""Generate a {difficulty.lower()} fill-in-the-blank question about '{topic}'.
Format as JSON:
{{
    "question": "the question with ___ for the blank",
    "answer": "the correct answer for the blank"
}}"""
                
                response = await async_generate(prompt)
                text = response.text.strip().replace("```json", "").replace("```", "").strip()
                quiz_data = json.loads(text)
                
                if "question" not in quiz_data or "answer" not in quiz_data:
                    raise ValueError("Invalid quiz format")
                
                embed = make_embed(
                    f"📝 Fill in the Blank: {topic} ({difficulty})",
                    f"{quiz_data['question']}\n\n💡 Type your answer in chat!",
                    color=0xe67e22
                )
                await ctx.followup.send(embed=embed)
                
                def check(m):
                    return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id
                
                try:
                    msg = await bot.wait_for('message', check=check, timeout=60.0)
                    user_answer = msg.content.strip().lower().replace(".", "").replace(",", "")
                    correct_answer = quiz_data["answer"].strip().lower().replace(".", "").replace(",", "")
                    
                    correct = user_answer == correct_answer
                    update_quiz_stats(ctx.author.id, topic, correct)
                    
                    if correct:
                        result_embed = make_embed("✅ Correct!", f"Perfect! The answer is: **{quiz_data['answer']}**", color=0x2ecc71)
                    else:
                        result_embed = make_embed("❌ Incorrect", f"The correct answer is: **{quiz_data['answer']}**", color=0xe74c3c)
                    
                    await ctx.send(embed=result_embed)
                    return
                except asyncio.TimeoutError:
                    timeout_embed = make_embed("⏰ Time's Up!", f"The correct answer was: **{quiz_data['answer']}**", color=0x95a5a6)
                    await ctx.send(embed=timeout_embed)
                    return
            
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            if attempt < max_retries - 1:
                continue
            await ctx.followup.send("⚠️ Error generating quiz. Please try again.")
            return
        except Exception as e:
            if attempt < max_retries - 1:
                continue
            await ctx.followup.send("⚠️ Could not generate quiz. Please try again.")
            return

@bot.slash_command(description="Create flashcards for studying")
async def flashcard(ctx, topic: Option(str, "Topic for flashcards")):
    await ctx.defer()
    try:
        prompt = f"""Create a study flashcard about '{topic}'.
Format as JSON:
{{
    "question": "the question/term",
    "answer": "detailed answer/definition"
}}"""
        
        response = await async_generate(prompt)
        card_data = json.loads(response.text.strip().replace("```json", "").replace("```", "").strip())
        
        if ctx.author.id not in user_flashcards:
            user_flashcards[ctx.author.id] = []
        
        card_with_meta = {
            "question": card_data["question"],
            "answer": card_data["answer"],
            "topic": topic,
            "created": datetime.now().isoformat(),
            "next_review": (datetime.now() + timedelta(days=1)).isoformat(),
            "interval": 1,
            "ease_factor": 2.5,
            "reviews": 0
        }
        user_flashcards[ctx.author.id].append(card_with_meta)
        
        embed = make_embed("🎴 Flashcard Created", card_data["question"], color=0x9b59b6)
        view = FlashcardView(card_data["question"], card_data["answer"], ctx.author.id)
        await ctx.followup.send(embed=embed, view=view)
        
    except Exception as e:
        await ctx.followup.send(f"⚠️ Could not create flashcard. Please try again.")

@bot.slash_command(description="Review flashcards due for study")
async def review(ctx):
    user_id = ctx.author.id
    
    if user_id not in user_flashcards or not user_flashcards[user_id]:
        await ctx.respond("📭 No flashcards to review. Create some with `/flashcard`!")
        return
    
    now = datetime.now()
    due_cards = [card for card in user_flashcards[user_id] 
                 if datetime.fromisoformat(card["next_review"]) <= now]
    
    if not due_cards:
        next_review = min(user_flashcards[user_id], 
                         key=lambda x: datetime.fromisoformat(x["next_review"]))
        next_time = datetime.fromisoformat(next_review["next_review"])
        time_until = next_time - now
        hours = int(time_until.total_seconds() / 3600)
        
        embed = make_embed(
            "✅ All Caught Up!",
            f"No cards due for review.\nNext review in {hours} hours.",
            color=0x2ecc71
        )
        await ctx.respond(embed=embed)
        return
    
    card = random.choice(due_cards)
    embed = make_embed(
        f"🎴 Review ({len(due_cards)} cards due)",
        card["question"],
        color=0x9b59b6
    )
    view = FlashcardView(card["question"], card["answer"], user_id, card_data=card, is_review=True)
    await ctx.respond(embed=embed, view=view)

@bot.slash_command(description="Get help with math problems")
async def math(ctx, problem: Option(str, "Your math problem")):
    await ctx.defer()
    try:
        prompt = f"Solve this math problem step by step: {problem}\nShow all work and explain each step clearly."
        response = await async_generate(prompt)
        embed = make_embed("🔢 Math Solution", response.text, color=0x3498db)
        await ctx.followup.send(embed=embed)
    except Exception:
        await ctx.followup.send("⚠️ Could not solve the problem.")

@bot.slash_command(description="Get help with science questions")
async def science(ctx, question: Option(str, "Your science question")):
    await ctx.defer()
    try:
        prompt = f"Explain this science concept in detail: {question}\nInclude examples and key principles."
        response = await async_generate(prompt)
        embed = make_embed("🔬 Science Explanation", response.text, color=0x1abc9c)
        await ctx.followup.send(embed=embed)
    except Exception:
        await ctx.followup.send("⚠️ Could not answer the question.")

@bot.slash_command(description="Practice problems for any subject")
async def practice(ctx, subject: Option(str, "Subject"), topic: Option(str, "Specific topic")):
    await ctx.defer()
    try:
        prompt = f"Create a practice problem for {subject} on the topic of {topic}. Include the problem and a detailed step-by-step solution."
        response = await async_generate(prompt)
        embed = make_embed(f"📚 Practice: {subject}", response.text, color=0xf39c12)
        await ctx.followup.send(embed=embed)
        
        if ctx.author.id not in user_study_stats:
            user_study_stats[ctx.author.id] = {"quizzes": 0, "practice": 0, "pomodoros": 0}
        user_study_stats[ctx.author.id]["practice"] += 1
    except Exception:
        await ctx.followup.send("⚠️ Could not generate practice problem.")

@bot.slash_command(description="Start a Pomodoro study timer")
async def pomodoro(ctx, minutes: Option(int, "Study duration in minutes", min_value=1, max_value=60) = 25):
    if ctx.author.id in active_pomodoro:
        await ctx.respond("⚠️ You already have an active timer!", ephemeral=True)
        return
    
    active_pomodoro[ctx.author.id] = datetime.now()
    embed = make_embed(
        f"⏰ Pomodoro Timer Started",
        f"Focus time: {minutes} minutes\nStay focused and avoid distractions!",
        color=0xe67e22
    )
    view = PomodoroView(ctx.author.id, minutes)
    await ctx.respond(embed=embed, view=view)
    
    await asyncio.sleep(minutes * 60)
    
    if ctx.author.id in active_pomodoro:
        del active_pomodoro[ctx.author.id]
        
        if ctx.author.id not in user_study_stats:
            user_study_stats[ctx.author.id] = {"quizzes": 0, "practice": 0, "pomodoros": 0}
        user_study_stats[ctx.author.id]["pomodoros"] += 1
        
        completion_embed = make_embed(
            "✅ Timer Complete!",
            f"Great work! You studied for {minutes} minutes.\nTime for a break! 🎉",
            color=0x2ecc71
        )
        await ctx.send(f"<@{ctx.author.id}>", embed=completion_embed)

@bot.slash_command(description="View your study statistics")
async def stats(ctx):
    user_id = ctx.author.id
    
    embed = discord.Embed(
        title=f"📊 Study Stats for {ctx.author.name}",
        description="Your comprehensive study overview",
        color=0x3498db
    )
    
    if user_id in user_quiz_scores:
        scores = user_quiz_scores[user_id]
        accuracy = (scores["correct"] / scores["total"] * 100) if scores["total"] > 0 else 0
        embed.add_field(
            name="📝 Quiz Performance",
            value=f"✅ Correct: {scores['correct']}\n❌ Total Attempted: {scores['total']}\n📈 Accuracy: {accuracy:.1f}%",
            inline=True
        )
        
        if scores["topics"]:
            top_topics = sorted(scores["topics"].items(), key=lambda x: x[1], reverse=True)[:3]
            topics_text = "\n".join([f"• {topic}: {count}" for topic, count in top_topics])
            embed.add_field(name="🏆 Top Topics", value=topics_text, inline=True)
    else:
        embed.add_field(name="📝 Quiz Performance", value="No data yet", inline=True)
    
    if user_id in user_study_stats:
        stats = user_study_stats[user_id]
        embed.add_field(
            name="📚 Study Activities",
            value=f"🎯 Quizzes: {stats.get('quizzes', 0)}\n📖 Practice: {stats.get('practice', 0)}\n⏰ Pomodoros: {stats.get('pomodoros', 0)}",
            inline=True
        )
    
    if user_id in user_flashcards and user_flashcards[user_id]:
        cards = user_flashcards[user_id]
        now = datetime.now()
        due_count = sum(1 for card in cards if datetime.fromisoformat(card["next_review"]) <= now)
        total_reviews = sum(card.get("reviews", 0) for card in cards)
        
        embed.add_field(
            name="🎴 Flashcards",
            value=f"📚 Total Cards: {len(cards)}\n🔄 Total Reviews: {total_reviews}\n⏰ Due Now: {due_count}",
            inline=True
        )
    
    total_activities = (
        user_quiz_scores.get(user_id, {}).get("total", 0) +
        user_study_stats.get(user_id, {}).get("practice", 0) +
        user_study_stats.get(user_id, {}).get("pomodoros", 0) +
        len(user_flashcards.get(user_id, []))
    )
    
    embed.set_footer(text=f"Total Study Actions: {total_activities} | Keep up the great work! 🎓")
    await ctx.respond(embed=embed)

@bot.slash_command(description="Get study tips and strategies")
async def studytips(ctx, subject: Option(str, "Subject you're studying") = None):
    await ctx.defer()
    try:
        if subject:
            prompt = f"Provide effective study tips and strategies specifically for {subject}."
        else:
            prompt = "Provide general study tips and strategies for academic success."
        
        response = await async_generate(prompt)
        embed = make_embed("💡 Study Tips", response.text, color=0xf39c12)
        await ctx.followup.send(embed=embed)
    except Exception:
        await ctx.followup.send("⚠️ Could not fetch study tips.")

@bot.slash_command(description="Summarize a topic or text")
async def summarize(ctx, content: Option(str, "Topic or text to summarize")):
    await ctx.defer()
    try:
        prompt = f"Provide a clear, concise summary of: {content}\nHighlight the key points."
        response = await async_generate(prompt)
        embed = make_embed("📋 Summary", response.text, color=0x95a5a6)
        await ctx.followup.send(embed=embed)
    except Exception:
        await ctx.followup.send("⚠️ Could not create summary.")

@bot.slash_command(description="Compare and contrast two concepts")
async def compare(ctx, concept1: Option(str, "First concept"), concept2: Option(str, "Second concept")):
    await ctx.defer()
    try:
        prompt = f"Compare and contrast '{concept1}' and '{concept2}'. Show similarities, differences, and key distinctions."
        response = await async_generate(prompt)
        embed = make_embed(f"⚖️ Comparison", response.text, color=0x16a085)
        await ctx.followup.send(embed=embed)
    except Exception:
        await ctx.followup.send("⚠️ Could not create comparison.")

@bot.slash_command(description="Export your study history and notes")
async def export(ctx):
    user_id = ctx.author.id
    export_data = []
    
    if ctx.channel.id in channel_history and channel_history[ctx.channel.id]:
        export_data.append("=== QUESTION & ANSWER HISTORY ===\n")
        for i, (q, a) in enumerate(channel_history[ctx.channel.id], 1):
            export_data.append(f"\nQ{i}: {q}")
            export_data.append(f"A{i}: {a}\n")
    
    if user_id in user_flashcards and user_flashcards[user_id]:
        export_data.append("\n=== FLASHCARDS ===\n")
        for i, card in enumerate(user_flashcards[user_id], 1):
            export_data.append(f"\nCard {i}:")
            export_data.append(f"Q: {card['question']}")
            export_data.append(f"A: {card['answer']}\n")
    
    if user_id in user_quiz_scores:
        scores = user_quiz_scores[user_id]
        accuracy = (scores["correct"] / scores["total"] * 100) if scores["total"] > 0 else 0
        export_data.append("\n=== QUIZ STATISTICS ===")
        export_data.append(f"\nCorrect Answers: {scores['correct']}")
        export_data.append(f"Total Attempts: {scores['total']}")
        export_data.append(f"Accuracy: {accuracy:.1f}%\n")
    
    if export_data:
        content = "\n".join(export_data)
        with open(f"study_export_{ctx.author.id}.txt", "w", encoding="utf-8") as f:
            f.write(content)
        
        with open(f"study_export_{ctx.author.id}.txt", "rb") as f:
            await ctx.respond(
                "📥 Here's your study data export!",
                file=discord.File(f, filename=f"study_notes_{ctx.author.name}.txt")
            )
        
        os.remove(f"study_export_{ctx.author.id}.txt")
    else:
        await ctx.respond("📭 No data to export yet. Start studying to build your history!")

@bot.slash_command(description="Show all available commands and features")
async def help(ctx):
    embed = discord.Embed(
        title="📚 Supreme Study Bot - Command Guide",
        description="Your ultimate AI-powered study companion!",
        color=0x3498db
    )
    
    embed.add_field(
        name="🎯 Core Study Commands",
        value=(
            "`/solve` - Get AI answers to any question\n"
            "`/explain` - Step-by-step explanations\n"
            "`/define` - Quick definitions\n"
            "`/summarize` - Summarize topics or texts\n"
            "`/compare` - Compare two concepts"
        ),
        inline=False
    )
    
    embed.add_field(
        name="📝 Quiz & Practice",
        value=(
            "`/quiz` - Generate quizzes (Multiple Choice/True-False/Fill-in-Blank)\n"
            "`/practice` - Get practice problems\n"
            "`/flashcard` - Create study flashcards\n"
            "`/review` - Review flashcards with spaced repetition"
        ),
        inline=False
    )
    
    embed.add_field(
        name="📊 Subject-Specific Help",
        value=(
            "`/math` - Solve math problems step-by-step\n"
            "`/science` - Science explanations with examples"
        ),
        inline=False
    )
    
    embed.add_field(
        name="⏰ Study Tools",
        value=(
            "`/pomodoro` - Start focus timer (default 25min)\n"
            "`/stats` - View your study statistics\n"
            "`/studytips` - Get study strategies\n"
            "`/history` - View recent Q&A in channel\n"
            "`/export` - Export your study notes"
        ),
        inline=False
    )
    
    embed.add_field(
        name="✨ Features",
        value=(
            "• Interactive quiz buttons\n"
            "• Progress tracking & statistics\n"
            "• Flashcard system\n"
            "• Pomodoro study timer\n"
            "• Subject specialization\n"
            "• Export study history"
        ),
        inline=False
    )
    
    embed.set_footer(text="💡 Tip: Use /quiz to test your knowledge on any topic!")
    await ctx.respond(embed=embed)

# =============================
# RUN
# =============================
keep_alive()
bot.run(BOT_TOKEN)
