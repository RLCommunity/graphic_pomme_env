"""Module to handle all of the graphics components.

'rendering' converts a display specification (such as :0) into an actual
Display object. Pyglet only supports multiple Displays on Linux.
"""
import os

import PIL.Image
import numpy as np
from PIL import Image

from typing import Tuple, List, Dict

from gym.error import ResetNeeded

from pommerman import constants
from pommerman.envs.v0 import Pomme

__location__ = os.path.dirname(os.path.realpath(constants.__file__))
RESOURCE_PATH = os.path.join(__location__, constants.RESOURCE_DIR)

STD_BOARD_SIZE = 11
STD_GRID_SIZE = 8
KEEP_MY_AGENT_SPRITE = constants.Item.Agent1.value #11


class PommeGraphic(Pomme):
    def __init__(self, *args, **argv):
        super(PommeGraphic, self).__init__(*args, **argv)
        self.sprite_size = argv['sprite_size']
        self.renres = load_resources(self.sprite_size)
        self.lastobs_raw = None

    def set_num_board_params(self, num_rigid:int=-1, num_wood:int=-1, num_items:int=-1):
        if num_rigid > 0:
            assert num_rigid % 2 == 0, "Requires an even number of rigid tiles"
            assert num_rigid >= 2, "The minimum number of rigid tiles that does not result in a crash is 2."
            self._num_rigid = num_rigid
        if num_wood > 0:
            assert num_wood % 2 == 0, "Requires an even number of wood tiles"
            assert num_wood >= 6, "The minimum number of wood tiles that does not result in a crash is 6."
            if self.spec.id == 'GraphicOneVsOne-v0':
                assert num_wood >= 10, "Minimum number of wood tiles for 8x8 board is 10."
            self._num_wood = num_wood
        if num_items > 0:
            assert num_items < self._num_wood, "Number of items shouls  be at most equal to the number of blocks."
            self._num_items = num_items

    def redraw(self, obs):
        # add agents own id to each observation, assume that they are mapped according to their position in the list
        for i, o in enumerate(obs):
            o['my_sprite'] = constants.Item.Agent0.value + i

        # preprocess the board
        ppboards = [preprocess_board(o) for o in obs]

        # render the boards
        raw_board_views = [postprocess_board(render_preprocessed_board(ppboard, self.renres),
                           self.renres, o['bomb_life'], ppboard) for ppboard, o in zip(ppboards, obs)]
        # render the dashboard on the bottom
        dash_views = [prepare_dashboard(o, self.renres, scale=self.sprite_size, board_size=self._board_size)
                      for o in obs]
        # concatenate them accordingly
        board_views = [np.concatenate([b, d], axis=0) for b, d in zip(raw_board_views, dash_views)]
        return board_views

    def reset(self):
        obs = super().reset()
        self.lastobs_raw = obs
        return self.redraw(obs)

    def step(self, actions):
        obs, reward, done, info = super().step(actions)
        self.lastobs_raw = obs
        return self.redraw(obs), reward, done, info

    def get_last_step_raw(self):
        if self.lastobs_raw:
            return self.lastobs_raw
        else:
            raise ResetNeeded("Trying to get a raw observation without resetting the env.")

    def render_tiled_observations(self, obs):
        '''
        Renders the current observation in a 2x2 grid, this function is for visual insepction only.
        :param obs:
        :return:
        '''
        images = [Image.fromarray(o) for o in obs]
        if len(images) == 4:
            return tile_four_images(images)
        elif len(images) == 2:
            return get_concat_h(*images)


def render_preprocessed_board(board: np.ndarray, resources: np.ndarray) -> np.ndarray:
    '''

    :param board: shape [board_size, board_size] ndarray, representing the board state (fully preprocessed)
    :param resources: shape [n, grid_size, grid_size, channels] ndarray, where n corresponds to the sprite number
    :return:
        a [board_size*grid_size, board_size*grid_size, channels] ndarray containing the rendered board
    '''
    inter1 = resources[board]
    inter2 = inter1.transpose(0, 2, 1, 3, 4)
    inter3 = inter2.reshape(board.shape[0]*resources.shape[1], board.shape[1]*resources.shape[2], resources.shape[3])
    return inter3


def preprocess_board(obs: Dict) -> np.ndarray:
    # in order for it to match the corresponding sprite number
    board = obs['board'].copy()
    bombs = obs['bomb_life']

    board[(bombs != 0) & ~__has_players(board)] = bombs[(bombs != 0) & ~__has_players(board)] + len(constants.FILE_NAMES)

    my_idx = obs['my_sprite'] #board[obs['position']]
    # substitute the other agent if he is alive
    if np.any(board == KEEP_MY_AGENT_SPRITE):
        board[board == KEEP_MY_AGENT_SPRITE] = my_idx
    # substitute self if self is alive
    if my_idx in obs['alive']:
        board[obs['position']] = KEEP_MY_AGENT_SPRITE

    return board


def postprocess_board(rendered_board: np.ndarray, res:np.ndarray, bombs:np.ndarray, ppboard: np.ndarray) -> np.ndarray:
    # establish the dimensions
    scale = res.shape[1]
    board_size = rendered_board.shape[0]//scale

    # look up whether there are bombs at player positions
    players = __where_agent(ppboard)
    for player in players:
        if bombs[player[0], player[1]] != 0:
            # render a small bar under the player
            rendered_board[__offset(player[0], scale)+__half_texture(scale)+__quarter_texture(scale): __offset(player[0]+1, scale), __offset(player[1], scale):__offset(player[1]+1, scale),:] =\
                __get_bomb(res, int(bombs[player[0], player[1]]))[__half_texture(scale)+__quarter_texture(scale):, :, :]

    return rendered_board


__has_players = lambda ppboard: (ppboard >= 9) & (ppboard <= 13)
__where_agent = lambda ppboard: np.transpose(np.nonzero(__has_players(ppboard))).tolist()
__get_texture = lambda res, index: res[index]
__get_bomb = lambda res, state: res[len(constants.FILE_NAMES) + state]
__offset = lambda x, scale: x*scale
__half_texture = lambda scale: scale//2
__quarter_texture = lambda scale: scale//4 + scale//8 # a bit more than a quarter :)

def prepare_dashboard(obs: Dict, res: np.ndarray,
                      scale: int = STD_GRID_SIZE, board_size: int = STD_BOARD_SIZE) -> np.ndarray:
    bs_sprite = 4
    ammo_sprite = 3
    conversion_array = np.zeros((1, board_size), dtype=np.int64)-1
    blast_strength = min(obs['blast_strength'], len(constants.BOMB_FILE_NAMES), board_size-(1 if board_size%2==1 else 0))
    can_kick = obs['can_kick']
    ammo = min(obs['ammo'], len(constants.BOMB_FILE_NAMES), board_size-(1 if board_size%2==1 else 2))
    # left is blast strength
    conversion_array[0, 0:(blast_strength+1)//2] = bs_sprite
    # right is ammo
    conversion_array[:, ::-1][0, 0:(ammo+1)//2] = ammo_sprite   # the id of the flame sprite
    # middle is kick capacity (if any)
    conversion_array[0, board_size//2] = 8 if can_kick > 0 else -1

    # color code those things a bit to be different from the rest of the thing
    rendered_array = render_preprocessed_board(conversion_array, res)

    # improve the bombs and explosion sprites on the bottom
    if blast_strength%2 == 1:
        bs = (blast_strength // 2)
        rendered_array[:, __offset(bs, scale)+__half_texture(scale):__offset(bs+1, scale), :] = 0
    if ammo%2 == 1:
        am = (ammo // 2)
        rendered_array[:, ::-1, :][:, __offset(am, scale)+__half_texture(scale):__offset(am+1, scale), :] = 0

    # grey out the panel in order to not repeat the sprites
    rendered_array[:, :, :] = rendered_array.mean(axis=2, keepdims=True)

    return rendered_array


def load_resources(sprite_size: int = STD_GRID_SIZE) -> np.ndarray:
    resource_array = np.zeros((len(constants.FILE_NAMES + constants.BOMB_FILE_NAMES)+1, sprite_size, sprite_size, 3), dtype=np.uint8)
    for i, name in enumerate(constants.FILE_NAMES+constants.BOMB_FILE_NAMES):
        sprite_img = Image.open(os.path.join(RESOURCE_PATH, name+'.png')).resize((sprite_size, sprite_size), resample=PIL.Image.NEAREST).convert('RGB')
        sprite_n = np.array(sprite_img)
        resource_array[i, :, :, :] = sprite_n
    return resource_array


# tow functions from https://note.nkmk.me/en/python-pillow-concat-images/ to help with display
def get_concat_h(im1, im2):
    dst = Image.new('RGB', (im1.width + im2.width, im1.height))
    dst.paste(im1, (0, 0))
    dst.paste(im2, (im1.width, 0))
    return dst


def get_concat_v(im1, im2):
    dst = Image.new('RGB', (im1.width, im1.height + im2.height))
    dst.paste(im1, (0, 0))
    dst.paste(im2, (0, im1.height))
    return dst


def get_board_and_bombs(obs: List) -> List:
    return [[o['board'], o['bomb_life']] for o in obs]


def tile_four_images(ims: List) -> Image:
    left = get_concat_v(ims[0], ims[1])
    right = get_concat_v(ims[2], ims[3])
    return get_concat_h(left, right)
