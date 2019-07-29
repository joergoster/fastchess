import chess
import re
import fastchess
import argparse
import random
import time
import mcts


def get_user_move(board):
    # Get well-formated move
    move = None
    while move is None:
        san_option = random.choice([board.san(m) for m in board.legal_moves])
        uci_option = random.choice([m.uci() for m in board.legal_moves])
        uci = input(f'Your move (e.g. {san_option} or {uci_option}): ')
        for parse in (board.parse_san, chess.Move.from_uci):
            try:
                move = parse(uci)
            except ValueError:
                pass

    # Check legality
    if move not in board.legal_moves:
        print('Illegal move.')
        return get_user_move(board)

    return move


def get_user_color():
    color = ''
    while color not in ('white', 'black'):
        color = input('Do you want to be white or black? ')
    return chess.WHITE if color == 'white' else chess.BLACK


def print_unicode_board(board, perspective=chess.WHITE):
    """ Prints the position from a given perspective. """
    print()
    uni_pieces = {
            'r':'♜', 'n':'♞', 'b':'♝', 'q':'♛', 'k':'♚', 'p':'♟',
            'R':'♖', 'N':'♘', 'B':'♗', 'Q':'♕', 'K':'♔', 'P':'♙',
            '.': ' ', ' ': ' ', '\n': '\n'}
    board_str = str(board)
    if perspective == chess.BLACK:
        board_str = '\n'.join(line[::-1] for line in board_str.split('\n')[::-1])
    colored = []
    for i, p in enumerate(board_str):
        if (i//2 + i//16) % 2 == 0: colored.append('\x1b[0;30;107m' + uni_pieces[p])
        if (i//2 + i//16) % 2 == 1: colored.append('\x1b[0;30;47m' + uni_pieces[p])
    lines = ''.join(colored).split('\n')
    sc, ec = '\x1b[0;30;107m', '\x1b[0m'
    if perspective == chess.WHITE:
        print('\n'.join(f' {sc} {8-i} {line} {sc} {ec}' for i, line in enumerate(lines)))
        print(f' {sc}   a b c d e f g h  {ec}\n')
    else:
        print('\n'.join(f' {sc} {1+i} {line} {sc} {ec}' for i, line in enumerate(lines)))
        print(f' {sc}   h g f e d c b a  {ec}\n')


def self_play(model, rand=False, debug=False, board=None):
    if not board:
        board = chess.Board()

    while not board.is_game_over():
        print_unicode_board(board)
        move = model.find_move(board, debug=debug, pick_random=rand)
        print(f' My move: {board.san(move)}')
        board.push(move)

    # Print status
    print_unicode_board(board)
    print('Result:', board.result())


def play(model, rand=False, debug=False, sleep=0, board=None):
    user_color = get_user_color()
    if not board:
        board = chess.Board()

    while not board.is_game_over():
        print_unicode_board(board, perspective = user_color)
        if user_color == board.turn:
            move = get_user_move(board)
        else:
            time.sleep(sleep)
            move = model.find_move(board, debug=debug, pick_random=rand)
            print(f' My move: {board.san(move)}')
        board.push(move)

    # Print status
    print_unicode_board(board, perspective = user_color)
    print('Result:', board.result())


class MCTS_Model:
    def __init__(self, fasttext_model, rolls, pvs=0):
        self.model = mcts.Model(fasttext_model)
        self.rolls = rolls
        self.pvs = pvs
        self.node = None

    def print_pvs(self):
        """ print `pvs` pvs starting from root """
        root = self.node
        pvs = min(self.pvs, len(root.children))
        for i in range(pvs):
            pv = []
            node = root
            while node.children:
                if node == root:
                    node = sorted(node.children, key=lambda n:-n.N)[i]
                    san = node.parent_board.san(node.move)
                    san += f' {node.N/root.N:.1%} ({float(-node.Q):.2})'
                else:
                    node = max(node.children, key=lambda n:n.N)
                    san = node.parent_board.san(node.move)
                pv.append(san)
            if len(pv) >= 10:
                pv = pv[:10] + ['...']
            print(f'Pv{i+1}:', ', '.join(pv))
        print("\u001b[1000D", end='') # Move left
        print(f"\u001b[{pvs}A", end='') # Move up

    def find_move(self, board, debug=False, pick_random=False):
        # We try to reuse the previous node, but if we can't, we create a new one.
        if self.node:
            # Check if the board is at one of our children (like pondering)
            for node in self.node.children:
                if node.board == board:
                    self.node = node
                    break

        # If we weren't able to find the board, make a new node
        if not self.node or self.node.board != board:
            self.node = mcts.Node(board, None, 0, self.model)
            if debug:
                print('Creating new node.')

        # Print priors for new root node
        if self.pvs:
            self.node.rollout() # Ensure children are expanded
            nodes = sorted(self.node.children, key=lambda n:n.P, reverse=True)[:7]
            print('Priors:', ', '.join(f'{board.san(n.move)} {n.P:.1%}' for n in nodes))

        # Find move to play
        for i in range(self.rolls):
            self.node.rollout()
            if self.pvs and (i % 100 == 0 or i == self.rolls-1):
                self.print_pvs()
        # Clean up
        if self.pvs:
            print('\n'*self.pvs, end='')
        if max(n.N for n in self.node.children)/self.node.N < .2:
            print('Thinking extra deeply.')
            return self.find_move(board, debug, pick_random)

        # Pick best or random child
        if pick_random:
            counts = [node.N for node in self.children]
            self.node = random.choices(self.node.children, weights=counts)[0]
        else:
            self.node = max(self.node.children, key = lambda n: n.N)

        return self.node.move


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('model_path', help='Location of fasttext model to use')
    parser.add_argument('-selfplay', action='store_true', help='Play against itself')
    parser.add_argument('-rand', action='store_true', help='Play random moves from predicted distribution')
    parser.add_argument('-debug', action='store_true', help='Print all predicted labels')
    parser.add_argument('-mcts', nargs='?', help='Play stronger (hopefully)', metavar='ROLLS', const=800, default=1, type=int)
    parser.add_argument('-pvs', nargs='?', help='Show Principal Variations (when mcts)', const=3, default=0, type=int)
    parser.add_argument('-fen', help='Start from given position', default='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1')
    args = parser.parse_args()

    if args.debug:
        print('Loading model...')
    fastchess_model = fastchess.Model(args.model_path)
    model = MCTS_Model(fastchess_model, rolls=args.mcts, pvs=args.pvs)
    board = chess.Board(args.fen)

    try:
        if args.selfplay:
            self_play(model, rand=args.rand, debug=args.debug, board=board)
        else:
            # If playing the model directly, we add a bit of sleep so the user can
            # see what's going on.
            play(model, rand=args.rand, debug=args.debug, board=board,
                    sleep = .3 if args.mcts < 100 else 0)
    except KeyboardInterrupt:
        pass
    finally:
        print('\nGoodbye!')

if __name__ == '__main__':
    main()

