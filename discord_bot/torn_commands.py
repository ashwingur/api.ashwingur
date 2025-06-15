import sys
from discord.ext import commands, tasks
import os
import aiohttp

V1_BASE_URL = "https://api.torn.com"
API_KEY = os.getenv("TORN_API_KEY")

GUILD_ID = 643314810640924672
CHANNEL_ID = 643314810640924675

class TornCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.shoplifting_status_update.start()
        # Flag to track if the "both true" message for Jewelry Store has been sent in the current cycle
        self.jewelry_store_both_true_notified = False

    def cog_unload(self):
        self.shoplifting_status_update.cancel()

    @tasks.loop(seconds=60)
    async def shoplifting_status_update(self):
        """
        Send a message to channel if theer are no cameras or guards enable in the Jewlry store
        """
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            print(f"Guild with ID {GUILD_ID} not found.", file=sys.stderr)
            return
        channel = guild.get_channel(CHANNEL_ID)
        if not channel:
            print(f"Channel with ID {CHANNEL_ID} not found.", file=sys.stderr)
            return

        url = f"{V1_BASE_URL}/torn/?selections=shoplifting&key={API_KEY}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    response.raise_for_status()  # Raise an exception for HTTP errors (4xx or 5xx)
                    data = await response.json()

            shoplifting_data = data.get("shoplifting", {})
            jewelry_store_items = shoplifting_data.get("jewelry_store", [])

            # Extract the 'disabled' status for "Three cameras" and "One guard"
            # Default to None if not found, to handle missing data gracefully
            cameras_disabled = None
            guard_disabled = None

            for item in jewelry_store_items:
                if item["title"] == "Three cameras":
                    cameras_disabled = item["disabled"]
                elif item["title"] == "One guard":
                    guard_disabled = item["disabled"]
            
            # Ensure both items were found in the API response
            if cameras_disabled is not None and guard_disabled is not None:
                # Condition: Both are currently true AND we haven't notified yet for this "both true" cycle
                if (
                    cameras_disabled is True
                    and guard_disabled is True
                    and not self.jewelry_store_both_true_notified
                ):
                    await channel.send(
                        f"🚨 **Jewelry Store** security status has changed! "
                        f"Both 'Three cameras' and 'One guard' are now **disabled** (true)."
                    )
                    self.jewelry_store_both_true_notified = True # Mark as notified for this cycle
                
                # Reset the notification flag if either item becomes false
                # This allows a new notification if they both become true again later
                elif (
                    cameras_disabled is False
                    or guard_disabled is False
                ):
                    self.jewelry_store_both_true_notified = False

        except aiohttp.ClientError as e:
            print(f"Error fetching data from Torn API: {e}", file=sys.stderr)
        except Exception as e:
            print(f"An unexpected error occurred: {e}", file=sys.stderr)

    @shoplifting_status_update.before_loop
    async def before_shoplifting_status_update(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(TornCommands(bot))