from abc import ABC
from copy import copy as shallowcopy

from ._round import AbstractRound, Round
from .enums import *


# Table assumes added players have enough funds to join.
# This should be taken care when Player is created from
# User, before joining a table.

class AbstractTable(ABC):
    RoundClass = AbstractRound

    def __init__(
        self, _id, seats,
        buyin, small_blind, big_blind
    ):
        self.id = _id
        self.seats = seats
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.buyin = buyin
        self.button = 0
        self.round = None

    @property
    def nplayers(self):
        return self.seats.nFilled()

    @property
    def nseats(self):
        return len(self.seats)

    def __repr__(self):
        return f'Table({self.seats})'

    def __bool__(self):
        return 2 <= self.nplayers <= self.nseats

    def __eq__(self, other):
        return self.id == other.id

    def __contains__(self, player):
        return player in self.seats

    def __getitem__(self, player_id):
        for p in self.seats:
            if player_id == p.id: return p
        if self.round:
            return self.round[player_id]

    def __iter__(self):
        return iter(self.seats)

    def __iadd__(self, player_or_player_with_index):
        if isinstance(player_or_player_with_index, tuple):
            player, index = player_or_player_with_index
            self._addPlayerOnSeat(player, index)
        else:
            self._addPlayer(player_or_player_with_index)
        return self

    def __isub__(self, player):
        self._removePlayer(player)
        return self

    def _addPlayer(self, player):
        seat_index = self.seats.append(player)
        if seat_index is not None:
            self.publicOut(
                TablePublicOutId.PLAYERJOINED,
                player_id = player.id,
                player_seat = seat_index
            )

    def _addPlayerOnSeat(self, player, index):
        if self.seats.seatPlayerAt(player, index):
            self.publicOut(
                TablePublicOutId.PLAYERJOINED,
                player_id = player.id,
                player_seat = index
            )

    def _shiftButton(self):
        self.button = (self.button + 1) % self.nplayers

    # kick out any player that has no money and
    # cannot get any from the current round played
    def _kickoutLosers(self):
        for p in self.seats:
            if p.money == 0 and (p.stake == 0 or p.is_folded):
                self._removePlayer(p)

    def _removePlayer(self, player):
        self.seats.remove(player)

        # if player is inside an active round: forcefold
        if self.round and player in self.round:
            if player.id == self.round.current_player.id:
                self.round.publicIn(
                    player.id, RoundPublicInId.FOLD
                )
            else:
                player.is_folded = True
                self.round._processState()

        self.publicOut(
            TablePublicOutId.PLAYERREMOVED,
            player_id = player.id,
        )

    def _newRound(self, round_id):
        self.round = self.RoundClass(
            round_id,
            self.seats.getPlayerGroup(),
            self.button,
            self.small_blind,
            self.big_blind
        )

    def _startRound(self, round_id):
        self._kickoutLosers()
        self._shiftButton()
        self._newRound(round_id)
        self.publicOut(
            TablePublicOutId.NEWROUNDSTARTED,
            round_id = round_id
        )

    def publicIn(self, player_id, action, **kwargs):
        """Override public in, to match the round's implementation"""
        ...

    def privateOut(self, player_id, out_id, **kwargs):
        """Override player out implementation"""
        # can be used to store additional table attributes
        ...

    def publicOut(self, out_id, **kwargs):
        """Override game out implementation"""
        # can be used to store additional table attributes
        ...

# add validators to the table operations
class ValidatedTable(AbstractTable):

    def __init__(
        self, _id, seats,
        buyin, small_blind, big_blind
    ):
        super().__init__(
            _id, type(seats)([None] * len(seats)),
            buyin, small_blind, big_blind
        )
        for seat in seats:
            if seat is not None:
                self._addPlayer(seat)

    def _addPlayer(self, player):
        self._kickoutLosers()
        if player.money < self.buyin: self.privateOut(
            player.id, TablePrivateOutId.BUYINTOOLOW,
            table_id=self.id)
        elif self.nplayers >= self.nseats: self.privateOut(
            player.id, TablePrivateOutId.TABLEFULL,
            table_id=self.id)
        elif player in self: self.privateOut(
            player.id, TablePrivateOutId.PLAYERALREADYATTABLE,
            table_id=self.id)
        else: super()._addPlayer(player)

    def _startRound(self, round_id):
        if self.round: self.publicOut(
            TablePublicOutId.ROUNDINPROGRESS,
            round_id=round_id, table_id=self.id)
        elif not self: self.publicOut(
            TablePublicOutId.INCORRECTNUMBEROFPLAYERS,
            round_id=round_id, table_id=self.id)
        else: super()._startRound(round_id)

class Table(ValidatedTable):
    RoundClass = Round

    def _forceOutRoundQueue(self):
        if self.round is None: return
        for msg in self.round.private_out_queue:
            self.privateOut(msg.player_id, msg.id, **msg.data)
        for msg in self.round.public_out_queue:
            self.publicOut(msg.id, **msg.data)
        self.round.private_out_queue.clear()
        self.round.public_out_queue.clear()

    def publicIn(self, player_id, action, **kwargs):

        if action in RoundPublicInId:
            if not self.round: self.publicOut(
                TablePublicOutId.ROUNDNOTINITIALIZED)
            else: self.round.publicIn(
                player_id, action, kwargs.get('raise_by'))

        elif action in TablePublicInId:
            if action is TablePublicInId.STARTROUND:
                self._startRound(kwargs.get('round_id'))
            elif action is TablePublicInId.LEAVETABLE:
                player = self.seats.getPlayerById(player_id)
                self._removePlayer(player)
            elif action is TablePublicInId.BUYIN:
                self._addPlayerOnSeat(kwargs['player'], kwargs['index'])

        # has to be done after every publicIn call
        self._forceOutRoundQueue()
        self._kickoutLosers()
