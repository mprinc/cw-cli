[Automatically opening multiple Apps / TABs for certain projects](https://apple.stackexchange.com/questions/142414/automatically-opening-multiple-apps-tabs-for-certain-projects)

[iTermocil](https://github.com/TomAnthony/itermocil)

[Launch iTerm with Window Arrangement by name via Applescript](https://gitlab.com/gnachman/iterm2/-/issues/3294)

[Opening a new terminal tab and running a command in it](https://talk.automators.fm/t/opening-a-new-terminal-tab-and-running-a-command-in-it/4839)

## Apple

[restorationClass](https://developer.apple.com/documentation/appkit/nswindow/1526241-restorationclass)
+ The restoration class associated with the window.

[NSWindowRestoration](https://developer.apple.com/documentation/appkit/nswindowrestoration)
+ A set of methods that restoration classes must implement to handle the recreation of windows.

https://developer.apple.com/documentation/appkit/nswindow/1526255-restorable

[Swindler](https://github.com/tmandry/Swindler)
+ A Swift window management library for macOS

## Install

```sh
source /Users/mprinc/data/development/common-dev-zontik/python/python3_env/bin/activate
# pip install iterm2
python3 -m pip install iterm2
pip install pyobjc
cd /Users/mprinc/data/development/colabo-zontik/colabo-lab/terminal/iTerm2/ContextualWalker
python3 ContextualWalker.py
```

Run as global

```sh
chmod og+x cw.sh
joe ~/.zshrc
alias cw="/Users/mprinc/data/development/colabo-zontik/colabo-lab/terminal/iTerm2/ContextualWalker/cw.sh"

source ~/.zshrc
```