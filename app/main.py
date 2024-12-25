import os
import openai
import json
import random
import asyncio
import discord
from discord.ext import commands
from typing import List, Dict, Optional, Tuple
from fastapi import FastAPI
import uvicorn
import logging  # ロギングモジュールをインポート

# ロギングの設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

API_KEY = os.getenv("OPENAI_API_KEY")
if API_KEY:
    logging.info("OPENAI_API_KEYが読み込まれました。")
else:
    logging.warning("OPENAI_API_KEYが設定されていません。")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if DISCORD_TOKEN:
    logging.info("DISCORD_TOKENが読み込まれました。")
else:
    logging.warning("DISCORD_TOKENが設定されていません。")

MODEL = "gpt-4o-mini"

class QuizGame:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model = model
        self.client = openai.OpenAI(api_key=api_key)
        
    async def ask_question(self, prompt: str, is_comparison: bool = False) -> str:
        logging.info("質問を送信: %s", prompt)  # 質問を送信する際にログを記録
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
            logging.error("OpenAI APIエラー: %s", str(e))  # エラーをログに記録
            return f"OpenAI APIエラー: {str(e)}"
        except Exception as e:
            logging.error("エラーが発生しました: %s", str(e))  # エラーをログに記録
            return f"エラーが発生しました: {str(e)}"

    async def get_responses(self, problem: str, solution: str, current_question: str, 
                          previous_question: Optional[str] = None) -> Tuple[str, str]:
        logging.info("問題: %s, 解答: %s, 現在の質問: %s", problem, solution, current_question)  # ログを記録
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
    def __init__(self, game: QuizGame):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        self.game = game
        self.active_games = {}

    async def setup_hook(self):
        @self.command(name='quiz', help='水平思考クイズを開始します')
        async def quiz(ctx):
            logging.info("クイズが開始されました。チャンネルID: %s", ctx.channel.id)  # ログを記録
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

                        await ctx.send(f"マスター: {regular_answer}")
                        if comparison_answer:
                            await ctx.send(f"質問の評価: {comparison_answer}")

                        self.active_games[ctx.channel.id]['previous_question'] = msg.content

                    except asyncio.TimeoutError:
                        await ctx.send('5分間質問がなかったため、クイズを終了します。')
                        del self.active_games[ctx.channel.id]
                        return

            await ctx.send("全ての問題が終了しました。お疲れさまでした！")
            del self.active_games[ctx.channel.id]

app = FastAPI()

@app.get("/health")
def health_check():
    return {"status": "OK"}

def main():
    game = QuizGame(API_KEY, MODEL)
    bot = QuizBot(game)

    # Discordボットを別スレッドで実行
    loop = asyncio.get_event_loop()
    loop.create_task(bot.start(DISCORD_TOKEN))

    # FastAPIを実行
    uvicorn.run(app, host="0.0.0.0", port=8080)

if __name__ == "__main__":
    main()
