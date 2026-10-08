#!/usr/bin/env python3.7

# iterm2 is a Python module (available on PyPI) that provides a nice interface to communicate with iTerm2
# The underlying implementation uses Google `protobuf` and `websockets`. 
# For most purposes, that is completely abstracted away.
import iterm2

# This script was created with the "basic" environment which **does not support adding dependencies**
# with pip.

async def get_all_sessions(app:iterm2.app.App):
    for window in app.windows:
        window_title = (await window.async_get_variable("titleOverride"))
        print("window title: %s" % (window_title))
        # add window title sufix
        # await window.async_set_title(window_title+" ;)")
        # remove the added window title sufix
        # await window.async_set_title(window_title[0:-3])
        # print("window detailed: %s" % (window.pretty_str()))
        for tab in window.tabs:
            tab_title = (await tab.async_get_variable("titleOverride"))
            print("\t\ttab title: %s" % (tab_title))
            for session in tab.sessions:
                # https://iterm2.com/documentation-session-title.html
                # https://stackoverflow.com/questions/56069701/how-do-i-get-and-set-the-titles-of-the-window-tab-and-session-in-iterm-2-with
                # https://iterm2.com/python-api/session.html#iterm2.Session.async_get_variable
                session_title = (await session.async_get_variable("autoName"))
                print("\t\t\tsession title: %s" % (session_title))
                if session_title == "colabo-GIST":
                    print("\t\t\t: changing session name: %s" % (session_title))
                    # https://iterm2.com/python-api/session.html#iterm2.Session.async_set_name
                    await session.async_set_name(session_title + "!")
                # await session.async_inject(code)

async def set_window_title(connection, app):
    window:iterm2.app.Window = app.current_terminal_window
    window_title = (await window.async_get_variable("titleOverride"))
    # https://www.iterm2.com/python-api/alert.html#iterm2.TextInputAlert
    alert = iterm2.TextInputAlert("Window title", "Enter the title for the current window.", "Window title", window_title, window.window_id)
    try:
        new_title = await alert.async_run(connection)
        await window.async_set_title(new_title)
    except e:
        print("WARNING - Could not edit window title")
        print(e)

async def save_window_to_arrangement(connection, app):
    window:iterm2.app.Window = app.current_terminal_window
    window_title = (await window.async_get_variable("titleOverride"))
    # https://www.iterm2.com/python-api/alert.html#iterm2.TextInputAlert
    alert = iterm2.TextInputAlert("Saving window as an arrangement", "Provide the name of the arrangement you want to save the window into.", "Window arrangement name", window_title, window.window_id)
    try:
        arrangement_name = await alert.async_run(connection)
        await window.async_save_window_as_arrangement(arrangement_name)

        alertReport = iterm2.Alert("Success", "Window is successfully saved into the arrangement: " + arrangement_name, window.window_id)
        arrangement_name = await alertReport.async_run(connection)

    except e:
        print("WARNING - Could not save window as arrangement")
        print(e)

async def restore_window_from_arrangement(connection, app):
    window:iterm2.app.Window = app.current_terminal_window
    window_title = (await window.async_get_variable("titleOverride"))
    arrangements = await iterm2.Arrangement.async_list(connection)
    arrangements_str = str(arrangements)
    print("arrangements: %s" %(arrangements_str))
    # https://www.iterm2.com/python-api/alert.html#iterm2.TextInputAlert
    alert = iterm2.TextInputAlert("Restore window from arrangement", "Provide the name of the arrangement you want to restore the window from. " + arrangements_str, "Window arrangement name", window_title, window.window_id)
    try:
        arrangement_name = await alert.async_run(connection)
        await window.async_restore_window_arrangement(arrangement_name)
        #  Set the window title to match the arrangement name
        await window.async_set_title(arrangement_name)
    except e:
        print("WARNING - Could not restore window from arrangement")
        print(e)

# Your code goes inside main. 
# The first argument is a connection that holds the link to a running iTerm2 process.
# main gets called only after a connection is established. 
# If the connection terminates (e.g., if you quit iTerm2) then any attempt to use it will raise an exception and terminate your script
async def main(connection):
    # all communication with iterm2 is async
    # therefore to have "sync" form you need to user `await` keyword
    # get a reference to the iterm2.App object
    # It is a singleton that provides access to iTerm2’s windows, 
    # and in turn their tabs and sessions.
    # https://iterm2.com/python-api/app.html#iterm2.async_get_app
    # https://iterm2.com/python-api/app.html#iterm2.App
    app:iterm2.app.App = await iterm2.async_get_app(connection)

    # fetches the “current terminal window” from the app
    # The current terminal window is the terminal window 
    # (and not, for example, the preferences window or some other non-terminal window)
    # that receives keyboard input when iTerm2 is active
    window:iterm2.app.Window = app.current_terminal_window
    # If there are no terminal windows then 
    # iterm2.App.current_window() returns None.
    if window is not None:
        # If there is a current terminal window, add a tab to it. 
        # The new tab uses the default profile.
        # await window.async_create_tab()
        pass
    else:
        # You can view this message in the script console.
        # Select Scripts > Script Console in iTerm2
        # + You can also use it to terminate a misbehaving script
        print("No current window")

    window_title = (await window.async_get_variable("titleOverride"))

    # https://www.iterm2.com/python-api/alert.html#iterm2.TextInputAlert
    alert = iterm2.TextInputAlert("Choose the command to execute for the window: "+window_title, "al - load arrangement\nas - save arrangement\nr - report all sessions\ntw - set window title", "command", "", window.window_id)
    try:
        command_name = await alert.async_run(connection)
        if(command_name == 'al'):
            await restore_window_from_arrangement(connection, app)
        elif(command_name == 'as'):
            await save_window_to_arrangement(connection, app)
        elif(command_name == 'r'):
            await get_all_sessions(app)
        elif(command_name == 'r'):
            await get_all_sessions(app)
        elif(command_name == 'tw'):
            await set_window_title(connection, app)
    except e:
        print("WARNING - Could not restore window from arrangement")
        print(e)

async def main2(connection):
    a = iterm2.Alert("Hi", "Bye")
    a.add_button("First")
    a.add_button("Second")
    a.add_button("Third")
    result = await a.async_run(connection)
    print("result: %s" % (result))

# This makes a connection to iTerm2 and 
# invokes your main function in an asyncio event loop. 
# When main returns the program terminates.
iterm2.run_until_complete(main)
# iterm2.run_until_complete(main2)

# # https://docs.python.org/3/library/asyncio-task.html#asyncio.run
# import asyncio
# asyncio.run(main2())