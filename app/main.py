import openai
import json
import random
import asyncio
import discord
from discord.ext import commands
from typing import List, Dict, Optional, Tuple
import os
from fastapi import FastAPI
from threading import Thread
import uvicorn

# FastAPIのインスタンスを作成
app = FastAPI()

class QuizGame:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model = model
        self.client = openai.OpenAI(api_key=api_key)
        
    async def ask_question(self, prompt: str, is_comparison: bool = False) -> str:
        try:
            system_content = (
                "前回の質問と比べて、今回の質問が正解に対して近いと判断できれば「前回よりも良い質問です。」とだけ答えなさい。"
                "前回の質問よりも正解から遠いと判断できた場合は「前回よりも悪い質問ですね」とだけ答えなさい。"
            ) if is_comparison else (
                "以下の情報と例に基づいて、ユーザーの質問に「はい」、「いいえ」、"
                "曖昧な場合は「ギリギリそう」や「ギリギリ違う」"
                "とも答えてよいです。"
            )
            
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt}
            ]
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages
            )
            return response.choices[0].message.content.strip()
            
        except openai.APIError as e:
            return f"OpenAI APIエラー: {str(e)}"
        except Exception as e:
            return f"エラーが発生しました: {str(e)}"

    async def get_responses(self, problem: str, solution: str, current_question: str, 
                          previous_question: Optional[str] = None) -> Tuple[str, str]:
        prompt = f"## 問題\n{problem}\n\n## 真相\n{solution}\n\n## 質問\n{current_question}"
        regular_answer = await self.ask_question(prompt)
        
        comparison_answer = ""
        if previous_question:
            comparison_prompt = (
                f"## 問題\n{problem}\n\n"
                f"## 真相\n{solution}\n\n"
                f"## 前回の質問\n{previous_question}\n\n"
                f"## 今回の質問\n{current_question}"
            )
            comparison_answer = await self.ask_question(comparison_prompt, is_comparison=True)
            
        return regular_answer, comparison_answer

class QuizBot(commands.Bot):
    def __init__(self, game: QuizGame, questions_path: str):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        self.game = game
        self.active_games = {}

    async def setup_hook(self):
        # コマンドを直接定義
        @self.command(name='クイズ', help='水平思考クイズを開始します')
        async def quiz(ctx):
            if ctx.channel.id in self.active_games:
                await ctx.send("このチャンネルではすでにクイズが進行中です。")
                return

            self.active_games[ctx.channel.id] = {
                'previous_question': None,
                'current_problem': None
            }

            try:
                with open("./horizontal-bot/questions.json", 'r', encoding='utf-8') as f:
                    questions = json.load(f)
            except Exception as e:
                await ctx.send(f"問題の読み込みに失敗しました: {str(e)}")
                return

            random.shuffle(questions)
            await ctx.send("===== 水平思考クイズを始めます！ =====")

            for i, question in enumerate(questions, 1):
                problem = question.get('Question', '問題が見つかりません')
                solution = question.get('Truth', '解答が見つかりません')
                
                self.active_games[ctx.channel.id]['current_problem'] = question

                await ctx.send(f"\n**問題 {i}:** {problem}")
                await ctx.send("```\nコマンド:\n!ヒント - ヒントを表示\n!解答 - 答えを表示\n!スキップ - 次の問題へ\n!終了 - ゲームを終了\n\n質問をそのまま入力することもできます。\n```")

                while True:
                    try:
                        def check(m):
                            return m.channel.id == ctx.channel.id and not m.author.bot

                        msg = await self.wait_for('message', timeout=300.0, check=check)
                        content = msg.content.lower()

                        if content == "!終了":
                            await ctx.send("クイズを終了します。お疲れさまでした！")
                            del self.active_games[ctx.channel.id]
                            return
                        elif content == "!スキップ":
                            await ctx.send("問題をスキップします。")
                            self.active_games[ctx.channel.id]['previous_question'] = None
                            break
                        elif content == "!解答":
                            await ctx.send(f"解答: {solution}")
                            self.active_games[ctx.channel.id]['previous_question'] = None
                            break
                        elif content == "!ヒント":
                            await ctx.send("ヒント機能は現在実装されていません。")
                            continue
                        elif content.startswith('!'):
                            continue

                        regular_answer, comparison_answer = await self.game.get_responses(
                            problem,
                            solution,
                            msg.content,
                            self.active_games[ctx.channel.id]['previous_question']
                        )

                        await ctx.send(regular_answer)
                        if comparison_answer:
                            await ctx.send(f"質問の評価: {comparison_answer}")

                        self.active_games[ctx.channel.id]['previous_question'] = msg.content

                    except asyncio.TimeoutError:
                        await ctx.send('5分間質問がなかったため、クイズを終了します。')
                        del self.active_games[ctx.channel.id]
                        return

            await ctx.send("全ての問題が終了しました。お疲れさまでした！")
            del self.active_games[ctx.channel.id]

@app.get("/")
def read_root():
    return {"message": "Bot is running"}

@app.post("/send_message")
async def send_message(channel_id: int, content: str):
    channel = bot.get_channel(channel_id)
    if channel:
        await channel.send(content)
        return {"status": "success"}
    return {"status": "error", "message": "Channel not found"}

def start_bot():
    bot.run(os.environ.get("DISCORD_BOT_TOKEN"))

def start_api():
    uvicorn.run(app, host="0.0.0.0", port=8080)

async def main():
    API_KEY = os.environ.get("OPENAI_API_KEY")
    BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
    QUESTIONS_PATH = os.environ.get("QUESTIONS_PATH", "questions.json")
    MODEL = "gpt-4o-mini"

    if not API_KEY or not BOT_TOKEN:
        raise ValueError("APIキーまたはボットトークンが設定されていません。")

    game = QuizGame(API_KEY, MODEL)
    global bot
    bot = QuizBot(game, QUESTIONS_PATH)

    # ボットとAPIを別スレッドで起動
    Thread(target=start_bot).start()
    Thread(target=start_api).start()

if __name__ == "__main__":
    asyncio.run(main())
