import logging
import re
from typing import List

from telegram.ext import CallbackQueryHandler, Filters, MessageHandler, Updater
from telegram.ext.callbackcontext import CallbackContext
from telegram.ext.dispatcher import Dispatcher
from telegram.update import Update
from transitions import Machine, State
from transitions.core import Transition

from tbc.db_adapter import DbAdapter

logger = logging.getLogger(__name__)


class Constructor:
    """
    Main bot constructor class, which contains many operational fields: bot (telegram), update (telegram),
    state-machine fields, db_adapter for handling users' states and so on
    """
    START_STATE_NAME = '__start__'
    FREE_TEXT_TRIGGER = '__free_text__'
    PHOTO_TRIGGER = '__photo_trigger__'
    LOCATION_TRIGGER = '__location_trigger__'
    PASSING_TRIGGER = '__passing_trigger__'

    def __init__(self, token: str, db_adapter: DbAdapter):
        """
        :param token: toke of your bot (could be obtained within @BotFather in telegram).
        :param db_adapter: object of the original class DbAdapter (db_adapter.DbAdapter) or object of the inherited
            class from DbAdapter

        :type token: str
        :type db_adapter: DbAdapter
        """
        self.token: str = token
        self.update: Update = None
        self.state: State = None
        self.machine: Machine = None
        self.start_state: State = None
        self.states: List[State] = []
        self.transitions: List[Transition] = []
        self.db_adapter: DbAdapter = db_adapter
        self.updater: Updater = Updater(self.token)
        self.dispatcher: Dispatcher = self.updater.dispatcher

    def __handler(self, context: CallbackContext, update: Update, trigger: str):
        """
        Handler method which is activated when bot receives message (or another type of input) from user.
        This method uses self.db_adapter.
            1. It takes the current user's state from database.
            2. Then it sets this state to state machine.
            3. Then it executes the related machine handler (with given state and trigger)
            4. Finally it updates state in self.state and update user's state in database.
        """
        eff_user = update.effective_user
        logger.info('Handling user with id: {}'.format(eff_user.id))
        self.user = self.db_adapter.get_user(eff_user=eff_user)
        self.context = context
        self.update = update
        self.user.state = Constructor.START_STATE_NAME if not self.user.state else self.user.state

        if self.machine:
            self.machine.set_state(state=self.user.state, model=self)
        else:
            self.machine = Machine(
                model=self,
                states=self.states,
                initial=self.user.state,
                transitions=self.transitions
            )

        triggers = self.machine.get_triggers(self.state)
        matched_triggers = []
        for possible_trigger in triggers:
            if re.match(possible_trigger, trigger):
                matched_triggers.append(possible_trigger)

        if len(matched_triggers) == 0:
            trigger = Constructor.FREE_TEXT_TRIGGER
        elif len(matched_triggers) == 1:
            trigger = matched_triggers[0]
        else:
            raise ValueError(
                f'Proposed trigger {trigger} has more then one possible model\'s '
                f'matched triggers: {matched_triggers}'
            )

        self.machine.model.trigger(trigger, self)

        self.user.state = self.state
        self.db_adapter.commit_user(self.user)

        if Constructor.PASSING_TRIGGER in self.machine.get_triggers(self.state):
            self.__handler(self, update, Constructor.PASSING_TRIGGER)

    def __msg_handler(self, update, bot):
        """
        Executes self.__handler if bot receives text from user
        """
        trigger = update.message.text
        self.__handler(bot, update, trigger)

    def __photo_handler(self, update, context):
        """
        Executes self.__handler if bot receives photo from user
        """
        trigger = Constructor.PHOTO_TRIGGER
        self.__handler(context, update, trigger)

    def __location_handler(self, update, context):
        """
        Executes self.__handler if bot receives location from user
        """
        trigger = Constructor.LOCATION_TRIGGER
        self.__handler(context, update, trigger)

    def __clb_handler(self, update, context):
        """
        Executes self.__handler if bot receives callback data from user
        """
        trigger = update.callback_query.data
        self.__handler(context, update, trigger)

    def add_state(self, name, on_enter=None, on_exit=None):
        """
        Append new state to the bot's states list
        See transitions.State class docs for more details.
        """
        args = locals()
        del args['self']
        self.states.append(State(**args))

    def add_transition(self, trigger, source, dest, conditions=None, unless=None, before=None,
                       after=None, prepare=None):
        """
        Append new transitions to the bot's transitions list.
        See transitions.Transition class docs for more details.
        """
        args = locals()
        del args['self']
        self.transitions += [args]

    def main(self):
        """
        Execute this method when bot is ready
        """

        dp = self.dispatcher

        dp.add_handler(MessageHandler(Filters.text, self.__msg_handler))
        dp.add_handler(MessageHandler(Filters.command, self.__msg_handler))
        dp.add_handler(MessageHandler(Filters.photo, self.__photo_handler))
        dp.add_handler(MessageHandler(
            Filters.location, self.__location_handler))
        dp.add_handler(CallbackQueryHandler(callback=self.__clb_handler))

        self.updater.start_polling()
        self.updater.idle()
