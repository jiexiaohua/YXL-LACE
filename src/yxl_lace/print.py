def logo_out():
    print("""
██    ██ ██   ██   ██
 ██  ██   ██ ██    ██
  ████     ███     ██
   ██     ██ ██    ██
   ██    ██   ██   ███████
          
""")


def index_out():
    print('''   Welcome to the P2P project. Here, you can experience a programmer-exclusive, self-destructing messaging system with no central server and end-to-end encrypted private chat. Explore freely to discover more features.
''')
    
def operate_out():
    print('''please select your operation
(0) quit project         (1) creat RSA key pair
(2) connect user         (3) set default local port
(4) save user
''')

if __name__ == "__main__":
    logo_out()
    index_out()

