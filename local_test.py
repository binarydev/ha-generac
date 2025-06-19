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
    jar = aiohttp.CookieJar(unsafe=True,quote_cookie=False)
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