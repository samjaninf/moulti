import os
from queue import Queue
from typing import Any
from textual import work
from textual.app import ComposeResult
from textual.worker import get_current_worker
from rich.text import Text
from ..abstractstep.tui import AbstractStep
from ..moultilog import MoultiLog

ANSI_ESCAPE_SEQUENCE = '\x1b'

class Step(AbstractStep):
	"""
	This widget represents a step in a script, program or process.
	Visually speaking, it is essentially a collapsible text area surrounded
	with optional text lines.
	"""
	def __init__(self, id: str, **kwargs: str|int|bool): # pylint: disable=redefined-builtin
		self.log_widget = MoultiLog(highlight=False)

		self.min_height = 1
		self.max_height = 25

		super().__init__(id='step_' + id, **kwargs)

		self.color = ''

	def cli_action_append(self, kwargs: dict[str, Any], helpers: dict[str, Any]) -> tuple:
		if 'text' not in kwargs:
			helpers['reply'](done=False, error='missing text for append operation')
			return ()
		return self.append, '\n'.join(kwargs['text'])

	def cli_action_clear(self, _kwargs: dict[str, str|int|bool], _helpers: dict[str, Any]) -> tuple:
		return self.clear, # pylint: disable=trailing-comma-tuple

	def subcompose(self) -> ComposeResult:
		yield self.log_widget

	def update_properties(self, kwargs: dict[str, str|int|bool]) -> None:
		super().update_properties(kwargs)
		if 'text' in kwargs:
			self.clear()
			self.append(str(kwargs['text']))
		if 'min_height' in kwargs:
			self.min_height = int(kwargs['min_height'])
		if 'max_height' in kwargs:
			self.max_height = int(kwargs['max_height'])
		self.log_widget.styles.min_height = self.min_height
		self.log_widget.styles.max_height = self.max_height if self.max_height > 0 else None

	def clear(self) -> None:
		self.log_widget.clear()
		self.color = ''

	def append(self, text: str) -> None:
		# RichLog does not handle partial lines and thus always adds a trailing \n; therefore, we must strip one (and
		# only one) trailing \n, if present:
		if text and text[-1] == '\n':
			text = text[:-1]
		# If necessary, prepend the ANSI escape code for the color inherited from the last line:
		if self.color:
			text = self.color + text
		# Deal with colored text; the text_to_write variable is made necessary by mypy.
		text_to_write: str | Text = text
		if ANSI_ESCAPE_SEQUENCE in text:
			text_to_write = Text.from_ansi(text)
			self.color = Step.next_line_color(text, text_to_write)
		self.log_widget.write(text_to_write)

	@classmethod
	def next_line_color(cls, string: str, text: Text) -> str:
		return '' if string.endswith('\x1b[0m') else Step.last_character_color(text)

	@classmethod
	def last_character_color(cls, text: Text) -> str:
		# If the last span (if any) covers the last character...
		if text.spans and text.spans[-1].end == len(text):
			# ... return the ANSI escape code for its color:
			style = text.spans[-1].style
			assert not isinstance(style, str) # prevent calling render() on str
			return style.render('_').split('_')[0]
		return ''

	def cli_action_pass(self, kwargs: dict[str, str|int|bool], helpers: dict[str, Any]) -> tuple:
		if not helpers['file_descriptors']:
			helpers['reply'](done=False, error='missing file descriptor for pass operation')
			return ()
		# Set up a queue between two workers:
		# - one that reads data from the file descriptor and replies to the client;
		# - one that appends lines to the step.
		queue: Queue = Queue()
		self.append_from_queue(queue, helpers)
		self.append_from_file_descriptor_to_queue(queue, kwargs, helpers)
		return ()

	@work(thread=True)
	async def append_from_file_descriptor_to_queue(
		self,
		queue: Queue,
		kwargs: dict[str, Any],
		helpers: dict[str, Any],
	) -> None:
		current_worker = get_current_worker()
		error = None
		try:
			file_desc = helpers['file_descriptors'][0]
			# Read lines from the given file descriptor:
			with os.fdopen(file_desc, encoding='utf-8', errors='surrogateescape') as text_io:
				# Syscall-wise, Python will read(fd, buffer, count) where count = max(8192, read_size) - read_bytes.
				# But it will NOT return anything unless it has reached the hinted read size.
				# Out of the box, Moulti should strive to display lines as soon as possible, hence the default value of
				# 1. It remains possible to specify a larger value, e.g. when one knows there are going to be many
				# lines over a short timespan, e.g. "find / -ls".
				read_size = int(kwargs.get('read_size', 1))
				while data := text_io.read(read_size):
					if current_worker.is_cancelled:
						break
					queue.put_nowait(data)
				queue.put_nowait(None)
		except Exception as exc:
			error = str(exc)
			helpers['debug'](f'pass: {error}')
		helpers['reply'](done=error is None, error=error)

	@work(thread=True)
	async def append_from_queue(self, queue: Queue, helpers: dict[str, Any]) -> None:
		current_worker = get_current_worker()
		self.prevent_deletion += 1
		try:
			buffer = []
			while True:
				if current_worker.is_cancelled:
					break
				data = queue.get()
				if data is not None:
					# Buffer data to avoid queuing partial lines as, down the
					# line, RichLog.write() only handles complete lines:
					# look for the position of \n from the end of the string :
					eol = data.rfind('\n')
					if eol == -1: # no \n found, buffer the whole string:
						buffer.append(data)
					else:
						before = data[:eol]
						after = data[eol+1:]
						buffer.append(before)
						self.app.call_from_thread(self.append, ''.join(buffer))
						buffer.clear()
						if after:
							buffer.append(after)
				else:
					# Reached EOF: flush buffer and signal EOF:
					if buffer:
						self.app.call_from_thread(self.append, ''.join(buffer))
					break
		except Exception as exc:
			helpers['debug'](f'append_from_queue: {exc}')
		finally:
			self.prevent_deletion -= 1

	DEFAULT_CSS = AbstractStep.DEFAULT_COLORS + """
	Step {
		& MoultiLog {
			scrollbar-corner-color: $step_default;
		}
		&.success {
			& MoultiLog { scrollbar-corner-color: $step_success; }
		}
		&.warning {
			& MoultiLog { scrollbar-corner-color: $step_warning; }
		}
		&.error {
			& MoultiLog { scrollbar-corner-color: $step_error; }
		}
		&.debug {
			& MoultiLog { scrollbar-corner-color: $step_debug; }
		}
	}
	"""
MoultiWidgetClass = Step
