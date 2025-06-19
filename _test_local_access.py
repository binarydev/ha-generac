# This script is a standalone test for the Generac API client.
# It logs in to the Generac API using credentials from environment variables
# and prints the device data in JSON format using a custom JSON encoder.
# Make sure to set the environment variables GENERAC_USER and GENERAC_PASS before running this script
# to avoid hardcoding sensitive information in the script.
# This script is intended to be run outside of Home Assistant, for testing purposes.
# It uses the aiohttp library for asynchronous HTTP requests and custom JSON encoding for dataclasses.
# Ensure you have aiohttp installed in your environment.
# If you're using Home Assistant, aiohttp is already included.
# You can install it using pip: pip install aiohttp
import asyncio
import dataclasses
import json
import logging
import os
import aiohttp
from custom_components.generac.api import GeneracApiClient

logging.basicConfig(level=logging.DEBUG)


# Your custom JSON encoder
class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


# Async main logic
async def main():
    jar = aiohttp.CookieJar(unsafe=True, quote_cookie=False)
    async with aiohttp.ClientSession(cookie_jar=jar) as session:
        api = GeneracApiClient(
            os.environ["GENERAC_USER"], os.environ["GENERAC_PASS"], session
        )
        await api.login()
        device_data = await api.get_device_data()
        print(json.dumps(device_data, cls=EnhancedJSONEncoder))


# Run it using asyncio.run (preferred method in Python 3.7+)
if __name__ == "__main__":
    asyncio.run(main())
