using StackOverflowLibrary.Entities;

namespace StackOverflowLibrary
{
    public interface IStackOverflowAccessor
    {
        /// <summary>
        /// Gets the Ids of Questions created after the given date.
        /// </summary>
        /// <param name="createdAtOrAfterDate">The date questions should be created at or after</param>
        /// <returns>Collection of StackOverflow Question Ids</returns>
        Task<List<int>> GetQuestionIdsWithAnswers(DateTime createdAtOrAfterDate);

        /// <summary>
        /// Gets the Ids of Questions created after the given date, that were tagged with all of the provided tags.
        /// </summary>
        /// <param name="createdAtOrAfterDate">The date questions should be created at or after</param>
        /// <param name="mustHaveTags">The list of tags for questions to be retrieved</param>
        /// <returns>Collection of StackOverflow Question Ids</returns>
        Task<List<int>> GetQuestionIdsWithAnswers(DateTime createdAtOrAfterDate, string[] mustHaveTags);

        /// <summary>
        /// Gets a representation of a StackOverflow Question, along with Answers, with the given Id
        /// </summary>
        /// <param name="id">The Id of the Question</param>
        /// <returns>The representation of a StackOverflow Question</returns>
        Task<Question> GetQuestionById(int id);
    }
}