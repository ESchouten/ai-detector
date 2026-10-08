import { error } from '@sveltejs/kit';
import { isValiError } from 'valibot';
import { ConfigurationError } from '../../configuration.ts';
import { webLog } from '../web-log.ts';

/** Run a settings operation; what the person can correct is answered as a 400 with its message. */
export async function configurationAction<T>(operation: () => T | Promise<T>): Promise<T> {
	try {
		return await operation();
	} catch (failure) {
		if (failure instanceof ConfigurationError || isValiError(failure)) {
			webLog.info(/* @wc-ignore */ `Refused: ${failure.message}`);
			error(400, failure.message);
		}
		throw failure;
	}
}
