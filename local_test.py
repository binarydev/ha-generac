import asyncio
import dataclasses
import json
import logging
import os

import aiohttp
from custom_components.generac.api import GeneracApiClient

logging.basicConfig(level=logging.DEBUG)

jar = aiohttp.CookieJar(unsafe=True)


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


async def main():
    async with aiohttp.ClientSession(cookie_jar=jar) as session:
        api = GeneracApiClient(
            os.environ["GENERAC_USER"], os.environ["GENERAC_PASS"], session
        )
        await api.login()
        print(json.dumps(await api.get_device_data(), cls=EnhancedJSONEncoder))


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
