#!/usr/bin/env python3

import iterm2

# To install, update, or remove packages from PyPI, use Scripts > Manage > Manage Dependencies...

async def main(connection):
    print("starting")
    # Your code goes here. Here's a bit of example code that adds a tab to the current window:
    arrangements = await iterm2.Arrangement.async_list(connection)
    print("arrangements: %s" % (arrangements))

iterm2.run_until_complete(main)
