import aiohttp
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone

BASE_URL = "http://flask_app:5000"

class TransportOpenDataCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="parking", description="NSW live carpark data")
    @app_commands.describe(name="Parking name (optional)")
    async def parking(self, interaction: discord.Interaction, name: str = None):
        await interaction.response.defer()
        url = f"{BASE_URL}/transportopendata"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        await interaction.followup.send("Unable to fetch parking data")
                        return
                    
                    data = await resp.json()
                    data.sort(key=lambda x: x["name"])
                    if name:
                        name = name.lower()
                        filtered = [item for item in data if name in item.get("name", "").lower()]
                    else:
                        filtered = data
                    
                    if not filtered:
                        embed = discord.Embed(
                            title=f'Live Parking Data',
                            color=discord.Color.dark_grey(),
                            description=f"No data matching search '{name}'"
                        )
                        embed.timestamp = datetime.now(timezone.utc)
                        await interaction.followup.send(embed=embed)
                        return

                    chunked = [filtered[i:i+25] for i in range(0, len(filtered), 25)]

                    for i, chunk in enumerate(chunked):
                        embed = discord.Embed(
                            title=f'Live Parking Data{" (cont.)" if i > 0 else ""}',
                            color=discord.Color.dark_grey()
                        )
                        embed.timestamp = datetime.now(timezone.utc)

                        for item in chunk:
                            occ = item['occupancy']
                            cap = item['capacity']
                            percentage = f"{(occ / cap * 100):.0f}%"
                            indicator = "🟩"
                            if occ/cap > 0.85:
                                indicator = "🟥"
                            elif  occ/cap > 0.5:
                                indicator = "🟧"
                            name = item["name"].replace("Park&Ride - ", "")
                            embed.add_field(
                                name=f'{indicator} {name}',
                                value=f"{occ}/{cap} ({percentage})",
                                inline=False
                            )

                        await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

async def setup(bot):
    await bot.add_cog(TransportOpenDataCommands(bot))
